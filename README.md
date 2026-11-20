# video-editor

Speed up intervals, cut intervals and insert pauses in a video. A TOML file says what to do.
The original video is never changed.

## Requirements

- Python 3.11 or later. No packages to install.
- ffmpeg (`brew install ffmpeg`).

## Files

| File                 | Purpose                                                    |
|----------------------|------------------------------------------------------------|
| `edit_video.py`      | The script.                                                |
| `template.edit.toml` | The template for new configuration files. Do not put your edits here. |
| Your `.toml` files   | Your configuration files. Git ignores them, and it ignores video files. |

## Use

1. Create a configuration file from the template. Use one of these methods:

   - Let the script create `my_video.edit.toml` next to the video, with the
     video name filled in:

     ```sh
     python3 edit_video.py --new my_video.mov
     ```

   - Copy `template.edit.toml` to a name of your choice.

2. Edit the `[[edit]]` blocks in your configuration file. The file explains
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

## Choose the configuration file and the video

The script accepts any configuration file and any video:

```sh
python3 edit_video.py CONFIG                        # video from "input" in CONFIG
python3 edit_video.py CONFIG VIDEO                  # apply CONFIG to VIDEO
python3 edit_video.py CONFIG VIDEO --output FILE    # also choose the output file
```

- Without `VIDEO`, the fields `input` and `output` in the configuration file
  give the files. Relative paths start at the folder of the configuration file.
- With `VIDEO`, the script ignores `input` and `output`. The output is
  `VIDEO-NAME_edited.mp4` next to the video, unless `--output` gives a
  different file.
- `--plan` works with all three forms.

## Edits

| Action  | Fields                 | Result                                            |
|---------|------------------------|---------------------------------------------------|
| `speed` | `from`, `to`, `factor` | Plays the interval `factor` times faster.         |
| `cut`   | `from`, `to`           | Removes the interval from the output.             |
| `pause` | `at`, `seconds`        | Shows the frame at `at` for `seconds` seconds.    |

Each edit can have a `comment`. The timeline shows the comment. All times refer
to the original video. A pause can be inside a speed interval, but not inside
a cut interval. Speed intervals and cut intervals must not overlap. Audio is silent during speed intervals and pauses.

## Tests

```sh
python3 -m unittest
```
