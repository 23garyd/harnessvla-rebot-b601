"""Turn `cameras.json` into the `--robot.cameras` argument `lerobot-record` takes.

WHY DERIVE IT. Hand-writing that JSON would create a second description of the
cameras beside the manifest, and the two would drift. At that point
`cameras.json` documents a configuration no episode was recorded under, while
`CAMERA_SERIALS` pins something that was not used — and the pin regime would
report agreement about the wrong thing.

It is the same rule `URDF_EE_FRAME` follows: it is read from the driver rather
than written into the pin a second time, because a value that can disagree with
the one in use is not a pin.

THE NAMES ARE THE IMPORTANT PART. They become LeRobot observation keys and
through them the dataset feature names — `observation.images.agentview`. They
are frozen at record time, and renaming them afterwards invalidates every
episode recorded under the old name.

WHAT THIS DOES NOT COVER:

  - It does not open a camera or check one exists. `b601.cameras.preflight`
    does that, and should be run first.
  - It carries no exposure or gain: LeRobot's camera configs have no such
    fields, so `b601.cameras.capture` must apply them to the devices BEFORE
    recording starts. A recording made without that step runs under auto
    exposure no matter what the manifest says.
  - The D405's depth stream is deliberately absent; the manifest records colour
    only. Adding depth is a manifest change, not a change here.
"""

# Manifest backend -> the LeRobot camera type string it maps to. Both are
# registered via CameraConfig.register_subclass in the vendor tree.
_BACKENDS = {
    "v4l2": "opencv",
    "realsense": "realsense_d405_color",
}


class LerobotConfigError(Exception):
    """A camera could not be expressed as a LeRobot config. Never guess."""


def cameras_arg(cameras):
    """-> {name: config dict} for `lerobot-record --robot.cameras`."""
    out = {}
    for camera in cameras:
        kind = _BACKENDS.get(camera.backend)
        if kind is None:
            raise LerobotConfigError(
                f"{camera.name}: no LeRobot camera type is mapped for backend "
                f"{camera.backend!r}; known: {sorted(_BACKENDS)}. Refusing to "
                f"guess — the wrong type would point one driver at another's "
                f"address and fail in a way that looks like missing hardware")
        config = {
            "type": kind,
            "width": camera.width,
            "height": camera.height,
            "fps": camera.fps,
        }
        if kind == "opencv":
            # index_or_path, never an index. /dev/videoN renumbers across
            # replugs and demonstrably did on this machine: the D405 and the
            # webcam swapped ranges twice in one day.
            config["index_or_path"] = camera.device
        else:
            # By serial, because the D405's by-id path is not stable either —
            # it presents a different USB descriptor on USB 2 than on USB 3.
            config["serial_number_or_name"] = camera.serial
        out[camera.name] = config
    return out


def main(argv=None):
    """`python -m b601.cameras.lerobot_config` — print the argument.

    Exists so the recording script can interpolate it rather than restate it.
    """
    import json
    import sys
    from b601.cameras.config import CameraManifestError, load_cameras
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        print("usage: python -m b601.cameras.lerobot_config", file=sys.stderr)
        return 64
    try:
        print(json.dumps(cameras_arg(load_cameras())))
    except (CameraManifestError, LerobotConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
