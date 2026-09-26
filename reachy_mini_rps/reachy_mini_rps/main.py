"""Reachy Mini app: realtime rock-paper-scissors."""

import argparse
import io
import logging
import threading
import time

import numpy as np
from fastapi.responses import Response
from PIL import Image

from reachy_mini import ReachyMini, ReachyMiniApp
from reachy_mini_rps.game import Game
from reachy_mini_rps.gestures import majority
from reachy_mini_rps.hand_tracker import HandTracker, jpeg_with_points
from reachy_mini_rps.laptop_camera import LaptopCamera
from reachy_mini_rps.poses import pose_for
from reachy_mini_rps import speech
from reachy_mini_rps.voice import voice_active


logger = logging.getLogger(__name__)

_HOT_CHUNKS = 8
_SNAP_FRAMES = 6
_SNAP_INTERVAL_S = 0.05


def _blank_jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 18), (18, 20, 23)).save(buffer, format="JPEG")
    return buffer.getvalue()


_BLANK_JPEG = _blank_jpeg()


class RockPaperScissorsApp(ReachyMiniApp):
    """First-to-three rock-paper-scissors. Reachy throws with its head and antennas."""

    custom_app_url: str | None = "http://0.0.0.0:8042"
    request_media_backend: str | None = None

    def __init__(self, running_on_wireless: bool = False, laptop_camera: bool = False, no_mic: bool = False, local_sound: bool = False) -> None:
        super().__init__(running_on_wireless=running_on_wireless)
        self.laptop_camera = laptop_camera
        self.no_mic = no_mic
        self.local_sound = local_sound
        self._jpeg_lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._latest_frame: np.ndarray | None = None
        self._overlay_points: list[tuple[float, float, float]] | None = None
        self._overlay_label: object | None = None
        self._label_seq = 0

    def run(self, reachy_mini: ReachyMini, stop_event: threading.Event) -> None:
        game = Game()
        tracker = HandTracker()
        self._install_routes(game)
        if self.local_sound:
            import winsound
            reachy_mini.media.play_sound = lambda path: winsound.PlaySound(
                path, winsound.SND_FILENAME | winsound.SND_ASYNC
            )
        reachy_mini.media.start_recording()
        laptop: LaptopCamera | None = None
        preview: threading.Thread | None = None
        detector: threading.Thread | None = None
        hot_chunks = 0
        watching = False
        try:
            if self.laptop_camera:
                laptop = LaptopCamera()
                laptop.open()
            preview = threading.Thread(
                target=self._preview_loop,
                args=(reachy_mini, stop_event, laptop),
                name="rps-preview",
                daemon=True,
            )
            detector = threading.Thread(
                target=self._detect_loop,
                args=(tracker, stop_event),
                name="rps-hands",
                daemon=True,
            )
            preview.start()
            detector.start()
            while not stop_event.is_set():
                if game.phase == "idle":
                    hot_chunks, watching = self._idle(reachy_mini, game, hot_chunks, watching)
                elif game.phase == "countdown":
                    self._countdown(reachy_mini, game, stop_event)
                    if stop_event.is_set():
                        break
                    game.start_snap()
                elif game.phase == "snap":
                    self._snap(game, stop_event)
                elif game.phase == "reveal":
                    self._reveal(reachy_mini, game, stop_event)
        finally:
            stop_event.set()
            if preview is not None:
                preview.join(timeout=1.0)
            if detector is not None:
                detector.join(timeout=1.0)
            if laptop is not None:
                laptop.close()
            tracker.close()
            reachy_mini.media.stop_recording()

    def _preview_loop(
        self,
        reachy_mini: ReachyMini,
        stop_event: threading.Event,
        laptop: LaptopCamera | None,
    ) -> None:
        """Publish camera JPEGs without waiting on hand detection."""
        while not stop_event.is_set():
            if laptop is not None:
                frame = laptop.read()
            else:
                frame = reachy_mini.media.get_frame()
            if frame is None:
                continue
            copied = np.ascontiguousarray(frame)
            with self._jpeg_lock:
                points = self._overlay_points
                self._latest_frame = copied
            data = jpeg_with_points(copied, points)
            with self._jpeg_lock:
                self._jpeg = data

    def _detect_loop(self, tracker: HandTracker, stop_event: threading.Event) -> None:
        """Find the hand off the preview thread, and keep the latest dots."""
        while not stop_event.is_set():
            frame = self._latest_copy()
            if frame is None:
                time.sleep(0.03)
                continue
            label = tracker.read_throw(frame)
            points = None if tracker.last_points is None else list(tracker.last_points)
            with self._jpeg_lock:
                self._overlay_points = points
                self._overlay_label = label
                self._label_seq += 1

    def _latest_copy(self) -> np.ndarray | None:
        with self._jpeg_lock:
            frame = self._latest_frame
            if frame is None:
                return None
            return frame.copy()

    def _install_routes(self, game: Game) -> None:
        assert self.settings_app is not None

        @self.settings_app.get("/state")
        def state() -> dict[str, object]:
            return game.snapshot()

        @self.settings_app.post("/play")
        def play() -> dict[str, bool]:
            game.request_play()
            return {"ok": True}

        @self.settings_app.post("/stop")
        def stop() -> dict[str, bool]:
            game.request_stop()
            self.stop()
            return {"ok": True}

        @self.settings_app.get("/frame.jpg")
        def frame() -> Response:
            with self._jpeg_lock:
                payload = self._jpeg
            body = payload if payload is not None else _BLANK_JPEG
            return Response(content=body, media_type="image/jpeg")

    def _idle(
        self,
        reachy_mini: ReachyMini,
        game: Game,
        hot_chunks: int,
        watching: bool,
    ) -> tuple[int, bool]:
        if not watching:
            head, antennas = pose_for("watch")
            reachy_mini.goto_target(head=head, antennas=antennas, duration=0.5)
            watching = True

        if not self.no_mic and speech.accepting_mic():
            if voice_active(reachy_mini.media.get_audio_sample()):
                hot_chunks += 1
            else:
                hot_chunks = 0
        elif self.no_mic:
            hot_chunks = 0

        heard = hot_chunks >= _HOT_CHUNKS
        if (self.no_mic or speech.accepting_mic()) and (game.play_requested or heard):
            if game.begin_round():
                logger.info("Round started. Reachy throws %s", game.reachy_throw)
                return 0, False
        time.sleep(0.03)
        return hot_chunks, watching

    def _countdown(
        self,
        reachy_mini: ReachyMini,
        game: Game,
        stop_event: threading.Event,
    ) -> None:
        for beat in speech.COUNTDOWN_CLIPS:
            if stop_event.is_set():
                return
            if beat == "shoot":
                pose_name = game.reachy_throw or "watch"
            elif beat == "ready":
                pose_name = "watch"
            else:
                pose_name = "nod"
            head, antennas = pose_for(pose_name)
            reachy_mini.goto_target(head=head, antennas=antennas, duration=0.25)
            speech.say(reachy_mini.media, beat)

    def _snap(self, game: Game, stop_event: threading.Event) -> None:
        labels = []
        with self._jpeg_lock:
            seen = self._label_seq
        deadline = time.time() + 1.2
        while len(labels) < _SNAP_FRAMES and time.time() < deadline:
            if stop_event.is_set():
                break
            with self._jpeg_lock:
                seq = self._label_seq
                label = self._overlay_label
            if seq != seen:
                labels.append(label)
                seen = seq
            else:
                time.sleep(_SNAP_INTERVAL_S)
        voted = majority(labels)
        logger.info("Snap labels=%s vote=%s", labels, voted)
        game.finish_snap(voted)

    def _reveal(self, reachy_mini: ReachyMini, game: Game, stop_event: threading.Event) -> None:
        clips = game.reveal_clips()
        pose_name = game.reaction_pose()
        start = 0
        if clips and clips[0].startswith("i_choose_"):
            speech.say(reachy_mini.media, clips[0])
            start = 1
        if not stop_event.is_set():
            self._play_reaction(reachy_mini, pose_name)
        for clip in clips[start:]:
            if stop_event.is_set():
                break
            speech.say(reachy_mini.media, clip)
        game.back_to_idle()

    def _play_reaction(self, reachy_mini: ReachyMini, pose_name: str) -> None:
        head, antennas = pose_for(pose_name)
        reachy_mini.goto_target(head=head, antennas=antennas, duration=0.25)
        if pose_name == "win":
            flutter = np.array([0.2, -0.9], dtype=np.float64)
            reachy_mini.goto_target(head=head, antennas=flutter, duration=0.15)
            reachy_mini.goto_target(head=head, antennas=antennas, duration=0.15)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rock-paper-scissors against Reachy Mini.")
    parser.add_argument(
        "--laptop-camera",
        action="store_true",
        help="Watch the laptop camera instead of the Reachy camera. Motors, mic, and speaker stay on the robot.",
    )
    parser.add_argument(
        "--no-mic",
        action="store_true",
        help="Disable voice activation (for simulators without audio). Start rounds via POST /play.",
    )
    parser.add_argument(
        "--local-sound",
        action="store_true",
        help="Play WAV clips via Windows audio instead of the robot speaker.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    app = RockPaperScissorsApp(laptop_camera=args.laptop_camera, no_mic=args.no_mic, local_sound=args.local_sound)
    try:
        app.wrapped_run()
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    main()
