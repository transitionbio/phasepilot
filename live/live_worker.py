'''
Live analysis worker: turns camera frames into droplet data for the Live analysis tab while a screen runs.

For each new frame it splits the camera quadrants, subtracts background and corrects illumination,
detects droplets, measures each droplet's intensity in every channel, and classifies phase separation
with the pipeline CNN for up to --classify-per-frame droplets (CPU inference is ~25 droplets/s, so all
droplets only on a GPU). Processing reuses the analysis pipeline's own `phasescan` package, so results
match the pipeline's.

Results go to --out as part files the tab reads as they appear (LiveFolderSource):
  part_<first frame>.parquet   droplets: frame, time, x, y, radius, '488', '546', '647', phase_separated_prob,
                               and with --sam-checkpoint sam_area_ratio, sam_circularity, sam_score, sam_ok
                               (SAM droplet QC, see sam_qc.py; NaN on frames SAM skipped)
  sam_frames/frame_<n>.png     with --sam-checkpoint: frame n's fill channel with SAM outlines (green accepted,
                               red rejected) and detector circles (yellow), plus frame_<n>.json counts
  trace_<first frame>.parquet  frame, time, '488', '546', '647' (median droplet intensity per frame), n_droplets
  status.json                  frames processed, timings

Frames come from a Micro-Manager stack that is still being written (--stack) or a folder of
frame_<n>.npy files (--frames-dir, used for replays).

Requires the `phasescan` package (phasescan-cloud repo), opencv, torch and torchvision.
'''
import argparse
import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import skimage.io
import skimage.measure
import tifffile
import torch
import yaml
from phasescan import channel, config, droplet_batch, droplet_classification_cnn as cnn, image_preprocessing

FRAME_SHAPE = (1600, 1600)


class LocalFiles:
    '''
    Stands in for the S3 client in phasescan.config: "downloads" the calibration images from local paths.
    '''

    def __init__(self, paths):
        self.paths = paths

    def download_file(self, bucket, key, target):
        shutil.copy(self.paths[Path(key).name.split('_MMStack')[0]], target)


class FolderFrames:
    '''
    Frames saved as frame_<n>.npy; frame n is available once its file exists.
    '''

    def __init__(self, folder):
        self.folder = Path(folder)

    def available(self):
        return sorted(int(p.stem.split('_')[1]) for p in self.folder.glob('frame_*.npy'))

    def read(self, n):
        return np.load(self.folder / f'frame_{n:04d}.npy')

    def time(self, n):
        return (self.folder / f'frame_{n:04d}.npy').stat().st_mtime


class GrowingStack:
    '''
    A Micro-Manager stack that is still being written: pages are read as soon as they are complete.
    '''

    def __init__(self, path):
        self.path = Path(path)

    def available(self):
        if not self.path.exists():
            return []
        with tifffile.TiffFile(self.path, is_ome=False) as tif:
            n = 0
            try:
                for page in tif.pages:
                    if page.dataoffsets[0] + page.databytecounts[0] > self.path.stat().st_size:
                        break
                    n += 1
            except Exception:  # last page header still being written
                pass
        return list(range(n))

    def read(self, n):
        with tifffile.TiffFile(self.path, is_ome=False) as tif:
            return tif.pages[n].asarray()

    def time(self, n):
        '''
        Epoch time the camera delivered frame n, from Micro-Manager's per-image metadata (ReceivedTime).
        '''
        with tifffile.TiffFile(self.path, is_ome=False) as tif:
            tag = tif.pages[n].tags.get(51123)  # MicroManagerMetadata
            if tag is None:
                return np.nan
            meta = tag.value if isinstance(tag.value, dict) else json.loads(tag.value)
        received = meta.get('ReceivedTime')  # e.g. '2026-10-30 20:52:31.123 +0000'
        if not received:
            return np.nan
        return pd.Timestamp(received).timestamp()


def intensity_range(quadrant):
    '''
    Crop normalisation range, as in phasescan.droplet_classification_cnn.extract_droplets.
    '''
    lo = float(np.quantile(quadrant, 0.0))
    block = (round(quadrant.shape[0] / 8), round(quadrant.shape[1] / 8))
    hi = float(np.median(skimage.measure.block_reduce(quadrant, block, np.max)[1:-1, 1:-1]))
    return lo, hi


class LiveWorker:

    def __init__(self, args):
        self.args = args
        self.out = Path(args.out)
        self.out.mkdir(parents=True, exist_ok=True)
        cfg = yaml.safe_load(Path(args.config_common).read_text())
        self.cfg_droplets = yaml.safe_load(Path(args.config_droplets).read_text())
        tmp = Path(tempfile.mkdtemp())
        files = LocalFiles({Path(cfg['background_image']).name.split('_MMStack')[0]: args.background,
                            Path(cfg['illumination_image']).name.split('_MMStack')[0]: args.illumination})
        self.cfg = config.get_common_config(cfg, tmp, files)
        self.channels = self.cfg['channels_to_analyse']
        self.cls_cfg = config.ConfigCommon(cfg, None, background_image_local_path=Path(args.background),
                                           illumination_image_local_path=Path(args.illumination))
        self.background = self.cls_cfg.get_background_image()
        self.illumination = self.cls_cfg.get_illumination_image()
        self.cls_channel = channel.ChannelWaveLength.deserialize(args.classification_channel)
        self.target_size = cnn.CnnEfNetArch.input_size(cnn.CnnEfNetArch.ENET_B0)
        self.model, self.device = cnn.make_cnn_model(Path(args.model)) if args.model else (None, None)
        self.sam = None
        if args.sam_checkpoint:
            from phasecontrol.Live_Analysis.sam_qc import SamDropletQC
            self.sam = SamDropletQC(Path(args.sam_checkpoint))
        torch.set_num_threads(args.threads)
        self.rng = np.random.default_rng(0)
        self.status = {'frames_processed': 0, 'droplets': 0, 'classified': 0, 'detect_s': 0.0, 'classify_s': 0.0}

    def process(self, frames, stack, times):
        t0 = time.time()
        # image_stack_into_quadrants subtracts the background in place; classification needs the raw stack
        quadrants = image_preprocessing.image_stack_into_quadrants(
            stack.copy(), self.cfg['background_image'], self.cfg['quadrant_boundaries'],
            self.cfg['quadrant_transformations'], self.cfg['transformation_reference_quadrant'])
        quadrants = image_preprocessing.correct_illumination(quadrants, self.cfg['illumination_quadrants'])
        c = self.cfg_droplets
        detected = droplet_batch.detect_droplets_across_stacks(
            self.channels, quadrants, self.args.detection_channel, c['min_size'], c['max_size'],
            c['min_size_stddev'], c['max_size_stddev'], c['calc_shrink'],
            c.get('radius_estimate', 40), c.get('shrink_radius_by', 10))
        rows = []
        for n, d in zip(frames, detected):
            df = pd.DataFrame({'frame': n, 'time': times[n], 'x': d['x'], 'y': d['y'], 'radius': d['radius']})
            for i, ch in enumerate(self.channels):
                df[ch] = d['intensities_per_pixel'][:, i]
            rows.append(df)
        droplets = pd.concat(rows, ignore_index=True)
        droplets['phase_separated_prob'] = np.nan
        t1 = time.time()
        if self.model is not None and len(droplets):
            self.classify(frames, stack, droplets)
        t2 = time.time()
        if self.sam is not None:
            self.sam_check(frames, quadrants, droplets)
        t3 = time.time()

        trace = droplets.groupby('frame')[self.channels].median()  # as the pipeline's intensity_traces
        trace['n_droplets'] = droplets.groupby('frame').size()
        trace = trace.reindex(frames)
        trace.insert(0, 'time', [times[n] for n in frames])
        trace = trace.reset_index().rename(columns={'index': 'frame'})
        self.write(f'part_{frames[0]:05d}.parquet', droplets)
        self.write(f'trace_{frames[0]:05d}.parquet', trace)
        s = self.status
        s['frames_processed'] += len(frames)
        s['droplets'] += len(droplets)
        s['classified'] += int(droplets.phase_separated_prob.notna().sum())
        s['detect_s'] += t1 - t0
        s['classify_s'] += t2 - t1
        s['sam_s'] = s.get('sam_s', 0.0) + t3 - t2
        s['last_frame'] = int(frames[-1])
        (self.out / 'status.json').write_text(json.dumps(s))
        logging.info('frames %s-%s: %s droplets, detect %.1fs, classify %.1fs', frames[0], frames[-1],
                     len(droplets), t1 - t0, t2 - t1)

    def classify(self, frames, stack, droplets):
        '''
        Classify up to classify_per_frame droplets per frame with the pipeline CNN (crop as in the pipeline).
        '''
        cls_quadrants = cnn.preprocess_droplets_image_stack(
            stack, self.background, self.illumination, self.cls_cfg.quadrant_boundaries,
            self.cls_cfg.quadrant_transformations, self.cls_cfg.transformation_reference_quadrant, self.cls_channel)
        picks, crops = [], []
        for i, n in enumerate(frames):
            in_frame = droplets.index[droplets.frame == n].to_numpy()
            k = min(self.args.classify_per_frame, len(in_frame))
            chosen = self.rng.choice(in_frame, k, replace=False) if k < len(in_frame) else in_frame
            irange = intensity_range(cls_quadrants[i])
            for j in chosen:
                d = droplets.loc[j]
                crop, _ = cnn.extract_droplet((int(d.x), int(d.y)), int(round(d.radius * 1.25)), cls_quadrants[i],
                                              irange, self.target_size)
                picks.append(j)
                crops.append(crop)
        if crops:
            probs = cnn.cnn_classify(self.model, self.device, cnn.DropletStackDataset(np.array(crops)))
            droplets.loc[picks, 'phase_separated_prob'] = np.asarray(probs, float)

    def sam_check(self, frames, quadrants, droplets):
        '''
        SAM droplet QC on every sam_every-th frame (SAM encodes ~10 s per quadrant on CPU).
        '''
        from phasecontrol.Live_Analysis.sam_qc import SAM_COLUMNS
        for c in SAM_COLUMNS:
            droplets[c] = np.nan
        for i, n in enumerate(frames):
            if n % self.args.sam_every:
                continue
            in_frame = droplets.frame == n
            if in_frame.any():
                qc, pic = self.sam.check(np.asarray(quadrants[self.args.sam_channel])[i], droplets[in_frame], overlay=True)
                droplets.loc[qc.index, SAM_COLUMNS] = qc[SAM_COLUMNS].astype(float)
                # the picture the PhasePilot tab shows: camera image with SAM outlines and detector circles
                pics = self.out / 'sam_frames'
                pics.mkdir(exist_ok=True)
                skimage.io.imsave(pics / f'.frame_{n:05d}.png', pic, check_contrast=False)
                (pics / f'.frame_{n:05d}.png').replace(pics / f'frame_{n:05d}.png')
                (pics / f'frame_{n:05d}.json').write_text(json.dumps(dict(
                    frame=int(n), time=float(droplets.loc[in_frame, 'time'].iloc[0]),
                    checked=int(len(qc)), rejected=int((~qc.sam_ok.astype(bool)).sum()), channel=self.args.sam_channel)))

    def write(self, name, df):
        tmp = self.out / f'.{name}'
        df.to_parquet(tmp, index=False)
        tmp.rename(self.out / name)

    def run(self, source):
        done = set()
        idle_since = time.time()
        while True:
            new = [n for n in source.available() if n not in done and n >= self.args.from_frame
                   and n % self.args.every == 0]  # stride/skip so a slow worker keeps up with the camera
            if not new:
                if time.time() - idle_since > self.args.idle_exit:
                    return
                time.sleep(0.5)
                continue
            idle_since = time.time()
            for i in range(0, len(new), self.args.batch):
                frames = new[i:i + self.args.batch]
                self.process(frames, np.stack([source.read(n) for n in frames]), {n: source.time(n) for n in frames})
                done.update(frames)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument('--stack', help='Micro-Manager stack being written')
    src.add_argument('--frames-dir', help='folder of frame_<n>.npy files')
    parser.add_argument('--config-common', required=True, help='config-common YAML (quadrants, calibration images)')
    parser.add_argument('--config-droplets', required=True, help='config-droplets YAML (detection settings)')
    parser.add_argument('--background', required=True, help='local copy of the dark background stack')
    parser.add_argument('--illumination', required=True, help='local copy of the illumination stack')
    parser.add_argument('--model', help='CNN weights (.pth); omit to skip classification')
    parser.add_argument('--out', required=True)
    parser.add_argument('--detection-channel', default='647')
    parser.add_argument('--classification-channel', default='647')
    parser.add_argument('--classify-per-frame', type=int, default=10)
    parser.add_argument('--sam-checkpoint', help='SAM weights (sam_vit_b_01ec64.pth); adds the SAM droplet QC columns')
    parser.add_argument('--sam-every', type=int, default=10, help='run SAM on every n-th frame')
    parser.add_argument('--sam-channel', default='546', help='channel that fills the droplet, for SAM to outline')
    parser.add_argument('--batch', type=int, default=4, help='frames per processing batch')
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--idle-exit', type=float, default=60, help='stop after this many seconds without new frames')
    parser.add_argument('--every', type=int, default=1, help='process every n-th frame (keep up with the camera)')
    parser.add_argument('--from-frame', type=int, default=0, help='ignore frames before this index (skip a backlog)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    source = GrowingStack(args.stack) if args.stack else FolderFrames(args.frames_dir)
    LiveWorker(args).run(source)


if __name__ == '__main__':
    main()
