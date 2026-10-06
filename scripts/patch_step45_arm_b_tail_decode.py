from pathlib import Path

path = Path("scripts/extract_step45_arm_b_temporal_frames.py")
text = path.read_text(encoding="utf-8-sig")

old_signature = '''def _extract_case(
    video: Path,
    case_output: Path,
    case_plan: dict[str, Any],
    jpeg_quality: int,
) -> list[dict[str, Any]]:
'''

new_signature = '''def _extract_case(
    video: Path,
    case_output: Path,
    case_plan: dict[str, Any],
    jpeg_quality: int,
    tail_decode_tolerance_seconds: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
'''

if old_signature not in text:
    raise SystemExit("Expected _extract_case signature not found")

text = text.replace(
    old_signature,
    new_signature,
    1,
)

old_init = '''    extracted = []

    try:
'''

new_init = '''    extracted = []
    decode_unavailable = []

    try:
'''

if old_init not in text:
    raise SystemExit("Expected extracted initialization not found")

text = text.replace(
    old_init,
    new_init,
    1,
)

old_failure = '''            if not ok or image is None:
                raise RuntimeError(
                    "Could not decode "
                    f"frame {frame_number} "
                    f"from {video}"
                )
'''

new_failure = '''            if not ok or image is None:
                timestamp = float(
                    sample[
                        "timestamp_seconds"
                    ]
                )

                duration = float(
                    case_plan[
                        "duration_seconds"
                    ]
                )

                remaining = (
                    duration
                    - timestamp
                )

                if (
                    remaining >= 0
                    and remaining
                    <= tail_decode_tolerance_seconds
                ):
                    decode_unavailable.append(
                        {
                            "frame_number":
                                frame_number,
                            "timestamp_seconds":
                                timestamp,
                            "remaining_seconds":
                                round(
                                    remaining,
                                    6,
                                ),
                            "reason":
                                "source_frame_not_decodable",
                        }
                    )

                    continue

                raise RuntimeError(
                    "Could not decode "
                    f"frame {frame_number} "
                    f"from {video}; "
                    f"timestamp={timestamp:.6f}; "
                    f"remaining={remaining:.6f}"
                )
'''

if old_failure not in text:
    raise SystemExit("Expected decode failure block not found")

text = text.replace(
    old_failure,
    new_failure,
    1,
)

old_return = '''    return extracted
'''

new_return = '''    return (
        extracted,
        decode_unavailable,
    )
'''

if old_return not in text:
    raise SystemExit("Expected _extract_case return not found")

text = text.replace(
    old_return,
    new_return,
    1,
)

old_call = '''        extracted = _extract_case(
            video,
            case_output,
            case_plan,
            int(
                rules[
                    "jpeg_quality"
                ]
            ),
        )
'''

new_call = '''        (
            extracted,
            decode_unavailable,
        ) = _extract_case(
            video,
            case_output,
            case_plan,
            int(
                rules[
                    "jpeg_quality"
                ]
            ),
            float(
                rules[
                    "tail_decode_tolerance_seconds"
                ]
            ),
        )
'''

if old_call not in text:
    raise SystemExit("Expected _extract_case call not found")

text = text.replace(
    old_call,
    new_call,
    1,
)

old_manifest = '''                "sample_count":
                    len(
                        extracted
                    ),
                "frames":
                    extracted,
'''

new_manifest = '''                "planned_sample_count":
                    len(
                        case_plan[
                            "sampled_frames"
                        ]
                    ),
                "sample_count":
                    len(
                        extracted
                    ),
                "decode_unavailable_count":
                    len(
                        decode_unavailable
                    ),
                "decode_unavailable":
                    decode_unavailable,
                "frames":
                    extracted,
'''

if old_manifest not in text:
    raise SystemExit("Expected manifest case block not found")

text = text.replace(
    old_manifest,
    new_manifest,
    1,
)

old_print = '''        print(
            f"[WRITE] {case_id} "
            f"frames={len(extracted)}",
            flush=True,
        )
'''

new_print = '''        print(
            f"[WRITE] {case_id} "
            f"frames={len(extracted)} "
            f"decode_unavailable="
            f"{len(decode_unavailable)}",
            flush=True,
        )
'''

if old_print not in text:
    raise SystemExit("Expected write-status block not found")

text = text.replace(
    old_print,
    new_print,
    1,
)

path.write_text(
    text,
    encoding="utf-8",
    newline="\n",
)

print("PATCH PASS")
