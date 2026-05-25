# antelopev2 로 얼굴을 검출·임베딩하고, LightASD 점수망으로 트랙별 발화 점수를 뽑는 러너
# 얼굴 검출기는 antelopev2 하나로 통일(S3FD 미사용). 트래킹/크롭/ASD 점수 로직은 LightASD 에서 가져온다.
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import subprocess
import sys
import warnings
from pathlib import Path
from shutil import rmtree

import cv2
import numpy
import python_speech_features
import torch
import tqdm
from scipy import signal
from scipy.interpolate import interp1d
from scipy.io import wavfile

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LIGHTASD_DIR = PROJECT_ROOT / "third_party" / "Light-ASD"
FACE_ROOT = str(PROJECT_ROOT / "models" / "face")  # antelopev2 가 여기 models/antelopev2 에 있음
sys.path.insert(0, str(LIGHTASD_DIR))

from ASD import ASD  # noqa: E402  (LightASD 발화 점수망)
from insightface.app import FaceAnalysis  # noqa: E402
from scenedetect import ContentDetector, detect  # noqa: E402

warnings.filterwarnings("ignore")

FPS = 25  # LightASD 점수망은 25fps 기준


def scene_detect(video_file: str) -> list[tuple[int, int]]:
    scene_list = detect(video_file, ContentDetector())
    if not scene_list:
        cap = cv2.VideoCapture(video_file)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        return [(0, total)]
    return [(s.get_frames(), e.get_frames()) for s, e in scene_list]


def detect_faces(app: FaceAnalysis, frames_dir: str) -> list[list[dict]]:
    flist = sorted(glob.glob(os.path.join(frames_dir, "*.jpg")))
    dets: list[list[dict]] = []
    for fidx, fname in enumerate(tqdm.tqdm(flist, desc="antelope-detect")):
        img = cv2.imread(fname)  # BGR (insightface 기대 형식)
        faces = app.get(img)
        dets.append([
            {"frame": fidx, "bbox": f.bbox.tolist(), "conf": float(f.det_score), "emb": f.normed_embedding}
            for f in faces
        ])
    return dets


def bb_iou(a, b) -> float:
    x_a, y_a = max(a[0], b[0]), max(a[1], b[1])
    x_b, y_b = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x_b - x_a) * max(0, y_b - y_a)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / float(area_a + area_b - inter + 1e-9)


def _mean_embedding(embs: list) -> list:
    arr = numpy.asarray(embs, dtype=numpy.float32)
    mean = arr.mean(axis=0)
    norm = numpy.linalg.norm(mean) + 1e-9
    return (mean / norm).round(6).tolist()


def track_shot(scene_faces, min_track: int, num_failed_det: int, min_face: int) -> list[dict]:
    iou_thres = 0.5
    tracks = []
    while True:
        track = []
        for frame_faces in scene_faces:
            for face in frame_faces:
                if not track:
                    track.append(face)
                    frame_faces.remove(face)
                elif face["frame"] - track[-1]["frame"] <= num_failed_det:
                    if bb_iou(face["bbox"], track[-1]["bbox"]) > iou_thres:
                        track.append(face)
                        frame_faces.remove(face)
                        continue
                else:
                    break
        if not track:
            break
        if len(track) > min_track:
            frame_num = numpy.array([f["frame"] for f in track])
            bboxes = numpy.array([numpy.array(f["bbox"]) for f in track])
            frame_i = numpy.arange(frame_num[0], frame_num[-1] + 1)
            bboxes_i = numpy.stack([interp1d(frame_num, bboxes[:, ij])(frame_i) for ij in range(4)], axis=1)
            if max(numpy.mean(bboxes_i[:, 2] - bboxes_i[:, 0]), numpy.mean(bboxes_i[:, 3] - bboxes_i[:, 1])) > min_face:
                tracks.append({
                    "frame": frame_i,
                    "bbox": bboxes_i,
                    "embedding": _mean_embedding([f["emb"] for f in track]),
                })
    return tracks


def crop_video(track, crop_file: str, frames_dir: str, audio_path: str, crop_scale: float, threads: int) -> dict:
    flist = sorted(glob.glob(os.path.join(frames_dir, "*.jpg")))
    vout = cv2.VideoWriter(crop_file + "t.avi", cv2.VideoWriter_fourcc(*"XVID"), FPS, (224, 224))
    dets = {"x": [], "y": [], "s": []}
    for det in track["bbox"]:
        dets["s"].append(max((det[3] - det[1]), (det[2] - det[0])) / 2)
        dets["y"].append((det[1] + det[3]) / 2)
        dets["x"].append((det[0] + det[2]) / 2)
    dets["s"] = signal.medfilt(dets["s"], kernel_size=13)
    dets["x"] = signal.medfilt(dets["x"], kernel_size=13)
    dets["y"] = signal.medfilt(dets["y"], kernel_size=13)
    for fidx, frame in enumerate(track["frame"]):
        cs = crop_scale
        bs = dets["s"][fidx]
        bsi = int(bs * (1 + 2 * cs))
        image = cv2.imread(flist[frame])
        image = numpy.pad(image, ((bsi, bsi), (bsi, bsi), (0, 0)), "constant", constant_values=(110, 110))
        my, mx = dets["y"][fidx] + bsi, dets["x"][fidx] + bsi
        face = image[int(my - bs):int(my + bs * (1 + 2 * cs)), int(mx - bs * (1 + cs)):int(mx + bs * (1 + cs))]
        vout.write(cv2.resize(face, (224, 224)))
    vout.release()
    audio_tmp = crop_file + ".wav"
    audio_start, audio_end = track["frame"][0] / FPS, (track["frame"][-1] + 1) / FPS
    subprocess.call("ffmpeg -y -i %s -async 1 -ac 1 -vn -acodec pcm_s16le -ar 16000 -threads %d -ss %.3f -to %.3f %s -loglevel panic"
                    % (audio_path, threads, audio_start, audio_end, audio_tmp), shell=True)
    subprocess.call("ffmpeg -y -i %st.avi -i %s -threads %d -c:v copy -c:a copy %s.avi -loglevel panic"
                    % (crop_file, audio_tmp, threads, crop_file), shell=True)
    os.remove(crop_file + "t.avi")
    return {"track": track, "proc_track": dets}


def evaluate_network(crop_dir: str, pretrain_model: str) -> list:
    s = ASD()
    s.loadParameters(pretrain_model)
    s.eval()
    files = sorted(glob.glob(os.path.join(crop_dir, "*.avi")))
    all_scores = []
    duration_set = {1, 1, 1, 2, 2, 2, 3, 3, 4, 5, 6}
    for file in tqdm.tqdm(files, desc="asd-score"):
        name = os.path.splitext(os.path.basename(file))[0]
        _, audio = wavfile.read(os.path.join(crop_dir, name + ".wav"))
        audio_feature = python_speech_features.mfcc(audio, 16000, numcep=13, winlen=0.025, winstep=0.010)
        video = cv2.VideoCapture(os.path.join(crop_dir, name + ".avi"))
        video_feature = []
        while video.isOpened():
            ret, frames = video.read()
            if not ret:
                break
            face = cv2.cvtColor(frames, cv2.COLOR_BGR2GRAY)
            face = cv2.resize(face, (224, 224))[int(112 - 56):int(112 + 56), int(112 - 56):int(112 + 56)]
            video_feature.append(face)
        video.release()
        video_feature = numpy.array(video_feature)
        length = min((audio_feature.shape[0] - audio_feature.shape[0] % 4) / 100, video_feature.shape[0])
        audio_feature = audio_feature[:int(round(length * 100)), :]
        video_feature = video_feature[:int(round(length * 25)), :, :]
        all_score = []
        for duration in duration_set:
            batch_size = int(math.ceil(length / duration))
            scores = []
            with torch.no_grad():
                for i in range(batch_size):
                    input_a = torch.FloatTensor(audio_feature[i * duration * 100:(i + 1) * duration * 100, :]).unsqueeze(0).cuda()
                    input_v = torch.FloatTensor(video_feature[i * duration * 25:(i + 1) * duration * 25, :, :]).unsqueeze(0).cuda()
                    embed_a = s.model.forward_audio_frontend(input_a)
                    embed_v = s.model.forward_visual_frontend(input_v)
                    out = s.model.forward_audio_visual_backend(embed_a, embed_v)
                    scores.extend(s.lossAV.forward(out, labels=None))
            all_score.append(scores)
        all_scores.append(numpy.round(numpy.mean(numpy.array(all_score), axis=0), 1).astype(float))
    return all_scores


def main() -> None:
    parser = argparse.ArgumentParser(description="antelopev2 검출 + LightASD 점수망으로 트랙별 발화 점수 추출")
    parser.add_argument("video")
    parser.add_argument("output_json")
    parser.add_argument("--work-dir", default=None)
    parser.add_argument("--pretrain-model", default=str(LIGHTASD_DIR / "weight" / "pretrain_AVA_CVPR.model"))
    parser.add_argument("--min-track", type=int, default=10)
    parser.add_argument("--num-failed-det", type=int, default=10)
    parser.add_argument("--min-face", type=int, default=1)
    parser.add_argument("--crop-scale", type=float, default=0.40)
    parser.add_argument("--threads", type=int, default=10)
    args = parser.parse_args()

    video_in = os.path.abspath(args.video)
    output_json = os.path.abspath(args.output_json)
    work = Path(args.work_dir).resolve() if args.work_dir else Path(output_json).with_suffix("") / "work"
    frames_dir, crop_dir = str(work / "pyframes"), str(work / "pycrop")
    video_25, audio_16k = str(work / "video25.avi"), str(work / "audio16k.wav")
    if work.exists():
        rmtree(work)
    for d in (frames_dir, crop_dir):
        os.makedirs(d, exist_ok=True)

    subprocess.call("ffmpeg -y -i %s -qscale:v 2 -threads %d -async 1 -r %d %s -loglevel panic" % (video_in, args.threads, FPS, video_25), shell=True)
    subprocess.call("ffmpeg -y -i %s -qscale:a 0 -ac 1 -vn -threads %d -ar 16000 %s -loglevel panic" % (video_25, args.threads, audio_16k), shell=True)
    subprocess.call("ffmpeg -y -i %s -qscale:v 2 -threads %d -f image2 %s -loglevel panic" % (video_25, args.threads, os.path.join(frames_dir, "%06d.jpg")), shell=True)

    app = FaceAnalysis(name="antelopev2", root=FACE_ROOT, providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(640, 640))

    scenes = scene_detect(video_25)
    faces = detect_faces(app, frames_dir)
    all_tracks = []
    for start_f, end_f in scenes:
        if end_f - start_f >= args.min_track:
            all_tracks.extend(track_shot(faces[start_f:end_f], args.min_track, args.num_failed_det, args.min_face))
    print("scenes=%d tracks=%d" % (len(scenes), len(all_tracks)), file=sys.stderr)

    vid_tracks = [crop_video(t, os.path.join(crop_dir, "%05d" % i), frames_dir, audio_16k, args.crop_scale, args.threads)
                  for i, t in enumerate(tqdm.tqdm(all_tracks, desc="crop"))]
    scores = evaluate_network(crop_dir, args.pretrain_model)

    out_tracks = []
    for tidx, vt in enumerate(vid_tracks):
        track, proc, score = vt["track"], vt["proc_track"], scores[tidx]
        n = min(len(track["frame"]), len(score))
        frames_out = []
        for fidx in range(n):
            fr = int(track["frame"][fidx])
            cx, cy, cs = float(proc["x"][fidx]), float(proc["y"][fidx]), float(proc["s"][fidx])
            frames_out.append({
                "frame": fr, "t": round(fr / FPS, 3),
                "bbox": [round(cx - cs, 1), round(cy - cs, 1), round(cx + cs, 1), round(cy + cs, 1)],
                "score": round(float(score[fidx]), 3),
            })
        out_tracks.append({"track_id": tidx, "embedding": track["embedding"], "frames": frames_out})

    os.makedirs(os.path.dirname(output_json), exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as fh:
        json.dump({"fps": FPS, "video": video_in, "n_tracks": len(out_tracks), "tracks": out_tracks}, fh, ensure_ascii=False)
    print("wrote %s (tracks=%d)" % (output_json, len(out_tracks)), file=sys.stderr)


if __name__ == "__main__":
    main()
