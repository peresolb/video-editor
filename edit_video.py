#!/usr/bin/env python3
"""Speed up intervals and insert pauses in a video, driven by a TOML file.

Usage:
    python3 edit_video.py --new VIDEO      Create VIDEO-NAME.edit.toml from the template.
    python3 edit_video.py CONFIG           Produce the edited video.
    python3 edit_video.py CONFIG VIDEO     Apply CONFIG to VIDEO.
    python3 edit_video.py CONFIG --plan    Show the timeline only. Do not encode.

Without VIDEO, the fields "input" and "output" in CONFIG give the files. With
VIDEO, the script ignores these fields. The output is then VIDEO-NAME_edited.mp4
next to VIDEO, or the file that --output gives.

The script needs Python 3.11 or later and ffmpeg. It never writes to the input video.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

TEMPLATE = Path(__file__).with_name("template.edit.toml")
AUDIO_FORMAT = "aformat=sample_rates=48000:channel_layouts=stereo"


class ConfigError(Exception):
    """The configuration file contains an error that the user must correct."""


@dataclass(frozen=True)
class Segment:
    """One part of the output video.

    A segment with ``pause`` > 0 shows the source frame at ``start`` for
    ``pause`` seconds. Other segments play the source from ``start`` to ``end``
    at ``factor`` times the normal speed.
    """

    start: float
    end: float
    factor: float = 1.0
    pause: float = 0.0
    comment: str = ""

    @property
    def duration(self) -> float:
        """Return the length of the segment in the output video, in seconds."""
        return self.pause if self.pause else (self.end - self.start) / self.factor


def parse_time(value: object, duration: float) -> float:
    """Convert a time from the configuration to seconds.

    Accepted forms: a number of seconds, "mm:ss", "hh:mm:ss", each with
    optional decimals, and the words "start" and "end".
    """
    if isinstance(value, bool):
        raise ConfigError(f"Invalid time: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    if text == "start":
        return 0.0
    if text == "end":
        return duration
    try:
        seconds = 0.0
        for part in text.split(":"):
            seconds = seconds * 60 + float(part)
    except ValueError:
        raise ConfigError(
            f'Invalid time: {value!r}. Use seconds, "mm:ss" or "hh:mm:ss".'
        ) from None
    return seconds


def format_time(seconds: float) -> str:
    """Format seconds as h:mm:ss.d."""
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}:{minutes:02d}:{secs:04.1f}"


def build_segments(edits: list[dict], duration: float) -> list[Segment]:
    """Convert the edits from the configuration to an ordered list of segments.

    All times in the edits refer to the original video. A pause can be inside
    a speed interval. Speed intervals must not overlap.
    """
    speeds: list[tuple[float, float, float, str]] = []
    pauses: list[tuple[float, float, str]] = []
    for number, edit in enumerate(edits, start=1):
        label = f"Edit {number}"
        comment = str(edit.get("comment", ""))
        action = edit.get("action")
        try:
            if action == "speed":
                start = parse_time(edit["from"], duration)
                end = min(parse_time(edit["to"], duration), duration)
                factor = float(edit["factor"])
                if not 0 <= start < end:
                    raise ConfigError(f'{label}: "from" must be before "to".')
                if factor <= 0:
                    raise ConfigError(f'{label}: "factor" must be more than 0.')
                speeds.append((start, end, factor, comment))
            elif action == "pause":
                at = parse_time(edit["at"], duration)
                seconds = float(edit["seconds"])
                if not 0 <= at <= duration:
                    raise ConfigError(f'{label}: "at" is outside the video.')
                if seconds <= 0:
                    raise ConfigError(f'{label}: "seconds" must be more than 0.')
                pauses.append((at, seconds, comment))
            else:
                raise ConfigError(
                    f'{label}: "action" must be "speed" or "pause", not {action!r}.'
                )
        except KeyError as missing:
            raise ConfigError(f"{label}: the field {missing} is missing.") from None
        except ConfigError as error:
            if str(error).startswith(label):
                raise
            raise ConfigError(f"{label}: {error}") from None

    speeds.sort()
    for (_, first_end, _, _), (second_start, _, _, _) in zip(speeds, speeds[1:]):
        if second_start < first_end:
            raise ConfigError(
                f"Two speed intervals overlap at {format_time(second_start)}."
            )

    cuts = {0.0, duration}
    for start, end, _, _ in speeds:
        cuts.update((start, end))
    cuts.update(at for at, _, _ in pauses)
    ordered = sorted(cuts)

    def pauses_at(point: float) -> list[Segment]:
        return [
            Segment(start=at, end=at, pause=seconds, comment=comment)
            for at, seconds, comment in pauses
            if at == point
        ]

    segments = pauses_at(ordered[0])
    for start, end in zip(ordered, ordered[1:]):
        factor, comment = 1.0, ""
        for speed_start, speed_end, speed_factor, speed_comment in speeds:
            if speed_start <= start and end <= speed_end:
                factor, comment = speed_factor, speed_comment
        segments.append(Segment(start=start, end=end, factor=factor, comment=comment))
        segments.extend(pauses_at(end))
    return segments


def build_filter(
    segments: list[Segment], fps: float, duration: float, has_audio: bool
) -> str:
    """Build the ffmpeg filter graph that produces the output from the segments."""
    count = len(segments)
    last_frame = max(int(duration * fps) - 2, 0)
    video_inputs = "".join(f"[v{i}]" for i in range(count))
    chains = [f"[0:v]fps={fps},split={count}{video_inputs}"]
    normal = [i for i, s in enumerate(segments) if not s.pause and s.factor == 1.0]
    if has_audio and normal:
        audio_inputs = "".join(f"[a{i}]" for i in normal)
        chains.append(f"[0:a]asplit={len(normal)}{audio_inputs}")

    concat_inputs = ""
    for i, segment in enumerate(segments):
        if segment.pause:
            frame = min(round(segment.start * fps), last_frame)
            video = (
                f"trim=start_frame={frame}:end_frame={frame + 1},"
                f"setpts=PTS-STARTPTS,"
                f"tpad=stop_mode=clone:stop_duration={segment.pause:.3f},"
                f"trim=duration={segment.pause:.3f}"
            )
        else:
            video = (
                f"trim=start={segment.start:.3f}:end={segment.end:.3f},"
                f"setpts=(PTS-STARTPTS)/{segment.factor},fps={fps}"
            )
        chains.append(f"[v{i}]{video}[vo{i}]")
        concat_inputs += f"[vo{i}]"
        if has_audio:
            if i in normal:
                audio = (
                    f"[a{i}]atrim=start={segment.start:.3f}:end={segment.end:.3f},"
                    f"asetpts=PTS-STARTPTS,{AUDIO_FORMAT}"
                )
            else:
                audio = (
                    f"anullsrc=r=48000:cl=stereo,"
                    f"atrim=duration={segment.duration:.3f}"
                )
            chains.append(f"{audio}[ao{i}]")
            concat_inputs += f"[ao{i}]"

    audio_flag = 1 if has_audio else 0
    outputs = "[v][a]" if has_audio else "[v]"
    chains.append(f"{concat_inputs}concat=n={count}:v=1:a={audio_flag}{outputs}")
    return ";".join(chains)


def probe(video: Path) -> tuple[float, bool]:
    """Return the duration in seconds and whether the video has an audio track."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type", "-of", "json", str(video),
        ],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    has_audio = any(s.get("codec_type") == "audio" for s in data["streams"])
    return float(data["format"]["duration"]), has_audio


def print_plan(segments: list[Segment]) -> None:
    """Print the timeline: where each source part is found in the output."""
    print(f"{'Original':<23}{'New video':<23}{'Action':<12}Comment")
    position = 0.0
    for segment in segments:
        if segment.pause:
            source = format_time(segment.start)
            action = f"pause {segment.pause:g}s"
        else:
            source = f"{format_time(segment.start)}-{format_time(segment.end)}"
            action = "play" if segment.factor == 1.0 else f"speed {segment.factor:g}x"
        end = position + segment.duration
        new = f"{format_time(position)}-{format_time(end)}"
        print(f"{source:<23}{new:<23}{action:<12}{segment.comment}")
        position = end
    print(f"New length: {format_time(position)}")


def create_config(video: Path) -> Path:
    """Create a configuration file for ``video`` from the template."""
    if not video.is_file():
        raise ConfigError(f"The video does not exist: {video}")
    target = video.with_suffix(".edit.toml")
    if target.exists():
        raise ConfigError(f"{target} exists already. The script did not change it.")
    text = TEMPLATE.read_text(encoding="utf-8")
    text = text.replace("my_video.mov", video.name)
    text = text.replace("my_video_edited.mp4", f"{video.stem}_edited.mp4")
    target.write_text(text, encoding="utf-8")
    return target


def run(
    config_path: Path, video: Path | None, output_path: Path | None, plan_only: bool
) -> None:
    """Read the configuration and produce the edited video.

    ``video`` and ``output_path`` come from the command line and replace the
    fields "input" and "output" of the configuration.
    """
    if not config_path.is_file():
        raise ConfigError(f"The configuration file does not exist: {config_path}")
    try:
        config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{config_path.name} is not valid TOML: {error}") from None
    if video:
        source = video.resolve()
        output = source.with_name(f"{source.stem}_edited.mp4")
    elif "input" in config:
        source = (config_path.parent / config["input"]).resolve()
        default_output = f"{source.stem}_edited.mp4"
        output = (config_path.parent / config.get("output", default_output)).resolve()
    else:
        raise ConfigError(
            'No video. Give a video on the command line or set "input" in the file.'
        )
    if output_path:
        output = output_path.resolve()
    if not source.is_file():
        raise ConfigError(f"The input video does not exist: {source}")
    if output == source:
        raise ConfigError("The output must not be the same file as the input.")

    duration, has_audio = probe(source)
    fps = float(config.get("fps", 30))
    segments = build_segments(config.get("edit", []), duration)
    print_plan(segments)
    if plan_only:
        return

    temporary = output.with_name(f"{output.stem}.partial{output.suffix}")
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-stats", "-y",
        "-i", str(source),
        "-filter_complex", build_filter(segments, fps, duration, has_audio),
        "-map", "[v]",
    ]
    if has_audio:
        command += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    command += [
        "-c:v", "libx264", "-preset", str(config.get("preset", "veryfast")),
        "-crf", str(config.get("crf", 20)), "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(temporary),
    ]
    started = time.monotonic()
    try:
        subprocess.run(command, check=True)
    except (subprocess.CalledProcessError, KeyboardInterrupt):
        temporary.unlink(missing_ok=True)
        raise

    if output.exists() and config.get("keep_old_output", False):
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(output.stat().st_mtime))
        backup = output.with_name(f"{output.stem}_{stamp}{output.suffix}")
        output.rename(backup)
        print(f"Old version kept as {backup.name}")
    temporary.replace(output)
    print(f"Done in {time.monotonic() - started:.0f} s: {output}")


def main() -> int:
    """Run the command line interface."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("config", nargs="?", type=Path, help="the .edit.toml file")
    parser.add_argument("video", nargs="?", type=Path,
                        help='the video to edit, replaces "input" in the file')
    parser.add_argument("--output", type=Path, metavar="FILE",
                        help='the video to write, replaces "output" in the file')
    parser.add_argument("--new", type=Path, metavar="VIDEO",
                        help="create a configuration file for VIDEO")
    parser.add_argument("--plan", action="store_true",
                        help="show the timeline and do not encode")
    args = parser.parse_args()
    try:
        if args.new:
            print(f"Created {create_config(args.new)}")
        elif args.config:
            run(args.config, args.video, args.output, args.plan)
        else:
            parser.print_help()
            return 2
    except ConfigError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        print(f"Error: {error.cmd[0]} failed.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. The old output file did not change.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
