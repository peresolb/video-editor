# video-editor

Speed up intervals and insert pauses in a video. A small TOML file per video
says what to do. The original video is never changed.

## Requirements

- Python 3.11 or later. No packages to install.
- ffmpeg (`brew install ffmpeg`).

## Use

1. Create a configuration file for a video:

   ```sh
   python3 edit_video.py --new my_video.mov
   ```

   This creates `my_video.edit.toml` next to the video.

2. Edit the `[[edit]]` blocks in the configuration file. The file explains
   each field.

3. Optional: show the timeline without encoding.

   ```sh
   python3 edit_video.py my_video.edit.toml --plan
   ```

4. Produce the video:

   ```sh
   python3 edit_video.py my_video.edit.toml
   ```

To change the result, edit the configuration file and do step 4 again. The
script replaces the old output. Set `keep_old_output = true` to keep the old
output under a name with a timestamp.

## Edits

| Action  | Fields                 | Result                                            |
|---------|------------------------|---------------------------------------------------|
| `speed` | `from`, `to`, `factor` | Plays the interval `factor` times faster.         |
| `pause` | `at`, `seconds`        | Shows the frame at `at` for `seconds` seconds.    |

Each edit can have a `comment`. The timeline shows the comment. All times refer
to the original video.

## Tests

```sh
python3 -m unittest
```

Video files are in `.gitignore` and do not go into the repository.
