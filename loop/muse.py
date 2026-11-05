"""Muse step of the rig loop: Meta's Muse model reads the evidence and chooses one supported action.

Roles (as in the PhasePilot storyboard): the Bayesian planner proposes candidates; Muse reads the question,
limits, protein budget, run history and QC, and picks what to do next; the GUI's setpoint queue checks every
command against the instrument limits before the pumps move. Muse never sets pressures or flows directly:
it can only choose among these actions, and the driver turns the choice into a queued setpoint.

    run_candidate  <rank>    send the planner's candidate with this rank (0 = planner's top choice)
    replicate      <id>      repeat an earlier setpoint (uncertain or QC-flagged result)
    pause          <reason>  stop sending setpoints and ask the operator to look
    finish         <reason>  end the campaign (budget nearly spent, or the map has stopped changing)

The model is reached through Meta's Model API (OpenAI-compatible; any other compatible endpoint works too):
    MUSE_BASE_URL  default https://api.meta.ai/v1
    MUSE_MODEL     default muse-spark-1.3  (a reasoning model: it thinks before answering, and the API does not
                   return that hidden thinking, so Muse is asked to write its reasoning into the reply)
    MUSE_API_KEY   from the environment or a .env file next to this module (never logged)
If the call fails or the reply is not a valid action, the driver falls back to the planner's top candidate
and records that the fallback, not Muse, made the decision.
"""
import json
import os
from pathlib import Path
import re
import time
import urllib.request

ACTIONS = ('run_candidate', 'replicate', 'pause', 'finish')

SYSTEM = """You coordinate a closed-loop PhaseScan experiment at Transition Bio. PhaseScan mixes protein, \
RNA and a crowder in microfluidic droplets at flow-controlled ratios and images them; a classifier calls each \
droplet phase separated or mixed. The goal is to locate the phase boundary with as little protein as possible.

A Bayesian planner proposes candidate settings. You read the evidence and choose ONE action:
  run_candidate <rank>   send the planner candidate with that rank
  replicate <id>         repeat an earlier setpoint whose result is uncertain or failed QC
  pause <reason>         stop and ask the operator (droplet generation or image QC looks wrong)
  finish <reason>        end the campaign (protein budget nearly spent, or the map has stopped changing)
You cannot set flows or pressures yourself; the instrument controller checks every command.
Results arrive with a delay: droplets made at a setpoint reach the camera minutes later, and the analysis follows.
A setpoint marked IN FLIGHT has simply not been imaged yet; that is normal, not a failure. Judge the instrument on
results that are back and on the image QC line. Pausing stops the instrument and costs time, so use it only on
clear evidence of a problem.

Reply with JSON only:
{"reasoning": "<your step-by-step thinking in 3-6 short sentences: what the evidence and QC show, what each \
plausible action would buy for the boundary and what it would cost in protein, and why you choose this one>",
 "observation": "<one sentence on what the latest evidence shows>",
 "action": "<run_candidate|replicate|pause|finish>", "arg": <rank number, setpoint id, or reason>,
 "rationale": "<one or two sentences>"}"""


def env_file():
    path = Path(__file__).with_name('.env')
    if not path.exists():
        return {}
    return dict(line.strip().split('=', 1) for line in path.read_text().splitlines() if '=' in line)


class MuseClient:

    def __init__(self, base_url=None, model=None, api_key=None, timeout=180):
        env = {**env_file(), **os.environ}
        self.base_url = (base_url or env.get('MUSE_BASE_URL', 'https://api.meta.ai/v1')).rstrip('/')
        self.model = model or env.get('MUSE_MODEL', 'muse-spark-1.3')
        self.api_key = api_key or env.get('MUSE_API_KEY')
        self.timeout = timeout

    def chat(self, system, user):
        body = json.dumps({'model': self.model, 'max_tokens': 4000,
                           'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]})
        req = urllib.request.Request(f'{self.base_url}/chat/completions', data=body.encode(),
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': f'Bearer {self.api_key}'})
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            reply = json.loads(r.read())
        message = reply['choices'][0]['message']
        # some providers return the model's thinking trace (field name varies); Meta's API does not
        trace = message.get('reasoning') or message.get('reasoning_content') or ''
        self.last_usage = reply.get('usage', {})
        if not message.get('content'):
            raise RuntimeError(f'empty reply (finish_reason {reply["choices"][0].get("finish_reason")})')
        return message['content'], reply.get('model', self.model), time.time() - t0, trace

    def decide(self, brief, n_candidates, past_ids):
        """Returns (decision dict or None, record of the exchange for the decision log)."""
        record = {'muse_model': self.model, 'muse_endpoint': self.base_url, 'prompt': brief}
        if not self.api_key:
            record['muse_error'] = 'no MUSE_API_KEY'
            return None, record
        try:
            text, served_by, secs, trace = self.chat(SYSTEM, brief)
        except Exception as e:  # network, auth, provider errors: the loop must keep going
            record['muse_error'] = repr(e)
            return None, record
        record.update(muse_reply=text, muse_served_by=served_by, muse_seconds=round(secs, 1), muse_trace=trace,
                      muse_usage=getattr(self, 'last_usage', {}))
        decision, problem = parse(text, n_candidates, past_ids)
        if problem:
            record['muse_error'] = problem
        else:
            record['muse_reasoning'] = str(decision.get('reasoning', ''))
        return decision, record


def parse(text, n_candidates, past_ids):
    """Check Muse's reply is one supported action with a valid argument. Returns (decision, problem)."""
    m = re.search(r'\{.*\}', text, re.S)
    if not m:
        return None, 'reply has no JSON object'
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return None, f'reply JSON does not parse: {e}'
    action, arg = d.get('action'), d.get('arg')
    if action not in ACTIONS:
        return None, f'unsupported action {action!r}'
    if action == 'run_candidate':
        try:
            arg = int(arg)
        except (TypeError, ValueError):
            return None, f'run_candidate needs a rank, got {arg!r}'
        if not 0 <= arg < n_candidates:
            return None, f'rank {arg} out of range 0-{n_candidates - 1}'
    if action == 'replicate' and str(arg) not in past_ids:
        return None, f'replicate of unknown setpoint {arg!r}'
    d['arg'] = arg
    return d, None


def brief(question, budget, history, candidates, qc):
    """The evidence Muse reads, as a compact text table (not raw logs)."""
    lines = [f'QUESTION: {question}',
             f'PROTEIN: {budget["used_ul"]:.1f} of {budget["budget_ul"]:.1f} uL used '
             f'({budget["reserve_ul"]:.1f} uL reserve must stay in the syringe); '
             f'next setpoint costs ~{budget["next_ul"]:.2f} uL',
             '', 'RESULTS SO FAR (newest last; composition = flow fraction of the aqueous total):',
             'id    ' + '  '.join(f'{n:>6}' for n in budget['names']) +
             '  droplets  PS_frac  dye 488/546/647 (median droplet intensity)  QC']
    for h in history[-15:]:
        comp = '  '.join(f'{v:6.2f}' for v in h['x'])
        if h.get('in_flight'):
            lines.append(f'{h["id"]:<5} {comp}  IN FLIGHT (not imaged yet)')
            continue
        frac = '   n/a' if h.get('frac') is None else f'{h["frac"]:7.2f}'
        dyes = '/'.join('-' if h.get(f'I{c}') is None or h.get(f'I{c}') != h.get(f'I{c}') else f'{h[f"I{c}"]:.0f}'
                        for c in ('488', '546', '647'))
        lines.append(f'{h["id"]:<5} {comp}  {h.get("n", 0):8d}  {frac}  {dyes:>18}  {h.get("qc", "")}')
    if len(history) > 15:
        lines.insert(4, f'({len(history) - 15} older setpoints not shown)')
    lines += ['', 'IN FLIGHT (sent, results not back yet): ' + (', '.join(qc['in_flight']) or 'none'),
              f'IMAGE QC (last 5 min): {qc["summary"]}', '',
              'PLANNER CANDIDATES (rank, composition, predicted PS fraction mu, uncertainty sd, P(wrong side)):']
    for i, c in enumerate(candidates):
        mu = 'n/a' if c['mu'] is None else f'{c["mu"]:.2f}'
        sd = 'n/a' if c['sd'] is None else f'{c["sd"]:.2f}'
        comp = '  '.join(f'{v:.2f}' for v in c['x'])
        lines.append(f'{i}  {comp}  mu {mu}  sd {sd}  p_wrong {c["acq"]:.2f}  ({c["mode"]})')
    return '\n'.join(lines)
