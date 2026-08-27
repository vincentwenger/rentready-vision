import argparse
import json
from app.vision.video_processor import process_video


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--out", default="./local-output")
    args = parser.parse_args()
    manifest = process_video(args.video, args.out)
    print(json.dumps({"video": manifest["video"], "processing": manifest["processing"], "scenes": manifest["scenes"]}, indent=2))


if __name__ == "__main__":
    main()
