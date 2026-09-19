from __future__ import annotations

import hashlib
import json
import math
import re
from difflib import SequenceMatcher
from typing import Any, Callable

import cv2
import numpy as np

from .video_processor import feature_similarity, histogram_similarity, hsv_histogram, visual_signature


CONSOLIDATION_VERSION = "rentready-issue-consolidation/1.0"

DEFAULT_CONFIG: dict[str, float] = {
    "max_pair_gap_seconds": 12.0,
    "max_cluster_span_seconds": 20.0,
    "minimum_score": 0.68,
    "minimum_semantic_similarity": 0.40,
    "minimum_image_similarity": 0.55,
    "minimum_region_similarity": 0.50,
    "minimum_bbox_iou": 0.05,
    "maximum_bbox_center_distance": 0.22,
    "metadata_only_minimum_score": 0.78,
    "metadata_only_minimum_semantic_similarity": 0.65,
    "metadata_only_minimum_bbox_iou": 0.30,
}

SIGNAL_WEIGHTS: dict[str, float] = {
    "timestamp_similarity": 0.15,
    "room_similarity": 0.15,
    "category_similarity": 0.20,
    "image_similarity": 0.15,
    "region_similarity": 0.20,
    "semantic_similarity": 0.15,
}

_STOP_WORDS = {
    "a", "an", "and", "appears", "are", "at", "by", "in", "is", "it", "near",
    "of", "on", "possible", "possibly", "the", "there", "to", "visible", "visibly",
}
_TOKEN_ALIASES = {
    "discoloration": "stain",
    "discolored": "stain",
    "stained": "stain",
    "staining": "stain",
    "stains": "stain",
    "chipped": "chip",
    "chipping": "chip",
    "cracked": "crack",
    "cracking": "crack",
    "damaged": "damage",
}

ImageLoader = Callable[[str], bytes]


def consolidation_contract() -> dict[str, Any]:
    return {
        "version": CONSOLIDATION_VERSION,
        "signals": list(SIGNAL_WEIGHTS),
        "weights": dict(SIGNAL_WEIGHTS),
        "thresholds": dict(DEFAULT_CONFIG),
        "hard_gates": [
            "same normalized room",
            "same issue category",
            "pair timestamp gap within maximum",
            "cluster timestamp span within maximum",
            "spatial continuity through bbox overlap or center proximity",
        ],
        "image_similarity": "whole-frame HSV, dHash, and geometric ORB similarity",
        "region_similarity": "candidate-crop visual similarity combined with normalized bbox IoU",
        "semantic_similarity": "deterministic normalized-token and sequence similarity",
        "fallback": (
            "If image bytes cannot be loaded, merge only with stricter semantic, bbox, and "
            "aggregate-score thresholds. Missing visual evidence never receives a synthetic score."
        ),
        "auditability": {
            "raw_detections_preserved": True,
            "pairwise_signal_scores_preserved": True,
            "all_evidence_timestamps_preserved": True,
            "representative_is_highest_confidence": True,
        },
    }


def _tokens(value: Any) -> list[str]:
    words = re.findall(r"[a-z0-9]+", str(value or "").lower())
    return [_TOKEN_ALIASES.get(word, word) for word in words if word not in _STOP_WORDS]


def semantic_similarity(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    left_set = set(left_tokens)
    right_set = set(right_tokens)
    jaccard = len(left_set & right_set) / len(left_set | right_set)
    sequence = SequenceMatcher(None, " ".join(left_tokens), " ".join(right_tokens)).ratio()
    return round(max(jaccard, sequence), 5)


def bbox_iou(left: dict[str, Any], right: dict[str, Any]) -> float:
    try:
        lx1, ly1 = float(left["x"]), float(left["y"])
        lx2, ly2 = lx1 + float(left["width"]), ly1 + float(left["height"])
        rx1, ry1 = float(right["x"]), float(right["y"])
        rx2, ry2 = rx1 + float(right["width"]), ry1 + float(right["height"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    intersection = max(0.0, min(lx2, rx2) - max(lx1, rx1)) * max(
        0.0, min(ly2, ry2) - max(ly1, ry1)
    )
    union = max(0.0, (lx2 - lx1) * (ly2 - ly1)) + max(
        0.0, (rx2 - rx1) * (ry2 - ry1)
    ) - intersection
    return round(intersection / union, 5) if union > 0 else 0.0


def _bbox_center_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    try:
        left_center = (
            float(left["x"]) + float(left["width"]) / 2.0,
            float(left["y"]) + float(left["height"]) / 2.0,
        )
        right_center = (
            float(right["x"]) + float(right["width"]) / 2.0,
            float(right["y"]) + float(right["height"]) / 2.0,
        )
    except (KeyError, TypeError, ValueError):
        return math.inf
    return round(math.dist(left_center, right_center), 5)


def _decode_image(value: bytes) -> np.ndarray | None:
    if not value:
        return None
    encoded = np.frombuffer(value, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    return image if image is not None and image.size else None


def _dhash(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    return (resized[:, 1:] > resized[:, :-1]).reshape(-1)


def _visual_similarity(left: np.ndarray, right: np.ndarray) -> tuple[float, dict[str, Any]]:
    left_resized = cv2.resize(left, (320, 240), interpolation=cv2.INTER_AREA)
    right_resized = cv2.resize(right, (320, 240), interpolation=cv2.INTER_AREA)
    hsv_score = histogram_similarity(hsv_histogram(left_resized), hsv_histogram(right_resized))
    dhash_score = float(np.mean(_dhash(left_resized) == _dhash(right_resized)))
    left_signature = visual_signature(left_resized, analysis_width=320, max_orb_features=500)
    right_signature = visual_signature(right_resized, analysis_width=320, max_orb_features=500)
    features = feature_similarity(left_signature, right_signature)
    orb_score = features.get("similarity")
    if orb_score is None:
        score = 0.65 * hsv_score + 0.35 * dhash_score
    else:
        score = 0.45 * hsv_score + 0.25 * dhash_score + 0.30 * float(orb_score)
    return round(max(0.0, min(1.0, score)), 5), {
        "hsv_similarity": hsv_score,
        "dhash_similarity": round(dhash_score, 5),
        "orb_similarity": orb_score,
        "orb_good_matches": features.get("good_matches"),
        "orb_inlier_ratio": features.get("inlier_ratio"),
    }


def _crop(image: np.ndarray, bbox: dict[str, Any]) -> np.ndarray | None:
    height, width = image.shape[:2]
    try:
        x1 = max(0, min(width - 1, int(round(float(bbox["x"]) * width))))
        y1 = max(0, min(height - 1, int(round(float(bbox["y"]) * height))))
        x2 = max(x1 + 1, min(width, int(round((float(bbox["x"]) + float(bbox["width"])) * width))))
        y2 = max(y1 + 1, min(height, int(round((float(bbox["y"]) + float(bbox["height"])) * height))))
    except (KeyError, TypeError, ValueError):
        return None
    cropped = image[y1:y2, x1:x2]
    return cropped if cropped.size else None


def _evidence_key(issue: dict[str, Any]) -> str | None:
    evidence = issue.get("evidence")
    if isinstance(evidence, dict) and evidence.get("s3_key"):
        return str(evidence["s3_key"])
    return None


def _load_cached_image(
    issue: dict[str, Any],
    *,
    image_loader: ImageLoader | None,
    cache: dict[str, np.ndarray | None],
) -> np.ndarray | None:
    key = _evidence_key(issue)
    if not key or image_loader is None:
        return None
    if key not in cache:
        try:
            cache[key] = _decode_image(image_loader(key))
        except Exception:
            cache[key] = None
    return cache[key]


def compare_issues(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    image_loader: ImageLoader | None = None,
    image_cache: dict[str, np.ndarray | None] | None = None,
    config: dict[str, float] | None = None,
) -> dict[str, Any]:
    resolved = {**DEFAULT_CONFIG, **(config or {})}
    cache = image_cache if image_cache is not None else {}
    timestamp_gap = abs(float(left.get("timestamp") or 0.0) - float(right.get("timestamp") or 0.0))
    timestamp_similarity = max(0.0, 1.0 - timestamp_gap / resolved["max_pair_gap_seconds"])
    room_similarity = 1.0 if left.get("room") == right.get("room") else 0.0
    category_similarity = 1.0 if left.get("category") == right.get("category") else 0.0
    semantic_score = semantic_similarity(left.get("description"), right.get("description"))
    iou = bbox_iou(left.get("bbox") or {}, right.get("bbox") or {})
    center_distance = _bbox_center_distance(left.get("bbox") or {}, right.get("bbox") or {})

    left_image = _load_cached_image(left, image_loader=image_loader, cache=cache)
    right_image = _load_cached_image(right, image_loader=image_loader, cache=cache)
    image_score: float | None = None
    image_detail: dict[str, Any] | None = None
    crop_score: float | None = None
    crop_detail: dict[str, Any] | None = None
    if left_image is not None and right_image is not None:
        image_score, image_detail = _visual_similarity(left_image, right_image)
        left_crop = _crop(left_image, left.get("bbox") or {})
        right_crop = _crop(right_image, right.get("bbox") or {})
        if left_crop is not None and right_crop is not None:
            crop_score, crop_detail = _visual_similarity(left_crop, right_crop)

    if crop_score is None:
        region_score = iou
    else:
        region_score = 0.70 * crop_score + 0.30 * iou
    region_score = round(max(0.0, min(1.0, region_score)), 5)

    signal_values: dict[str, float | None] = {
        "timestamp_similarity": round(timestamp_similarity, 5),
        "room_similarity": room_similarity,
        "category_similarity": category_similarity,
        "image_similarity": image_score,
        "region_similarity": region_score,
        "semantic_similarity": semantic_score,
    }
    available_weight = sum(
        SIGNAL_WEIGHTS[name] for name, value in signal_values.items() if value is not None
    )
    weighted_score = sum(
        SIGNAL_WEIGHTS[name] * float(value)
        for name, value in signal_values.items()
        if value is not None
    ) / max(available_weight, 1e-9)

    reasons: list[str] = []
    if not room_similarity:
        reasons.append("different_room")
    if not category_similarity:
        reasons.append("different_category")
    if timestamp_gap > resolved["max_pair_gap_seconds"]:
        reasons.append("timestamp_gap_exceeded")
    spatially_continuous = (
        iou >= resolved["minimum_bbox_iou"]
        or center_distance <= resolved["maximum_bbox_center_distance"]
    )
    if not spatially_continuous:
        reasons.append("region_location_changed")

    visual_available = image_score is not None and crop_score is not None
    if visual_available:
        if image_score < resolved["minimum_image_similarity"]:
            reasons.append("whole_image_similarity_too_low")
        if region_score < resolved["minimum_region_similarity"]:
            reasons.append("region_similarity_too_low")
        if semantic_score < resolved["minimum_semantic_similarity"]:
            reasons.append("semantic_similarity_too_low")
        if weighted_score < resolved["minimum_score"]:
            reasons.append("weighted_score_too_low")
    else:
        if iou < resolved["metadata_only_minimum_bbox_iou"]:
            reasons.append("metadata_only_bbox_iou_too_low")
        if semantic_score < resolved["metadata_only_minimum_semantic_similarity"]:
            reasons.append("metadata_only_semantic_similarity_too_low")
        if weighted_score < resolved["metadata_only_minimum_score"]:
            reasons.append("metadata_only_score_too_low")

    return {
        "left_issue_id": left.get("issue_id"),
        "right_issue_id": right.get("issue_id"),
        "merge": not reasons,
        "score": round(weighted_score, 5),
        "signals": signal_values,
        "timestamp_gap_seconds": round(timestamp_gap, 3),
        "bbox_iou": iou,
        "bbox_center_distance": center_distance if math.isfinite(center_distance) else None,
        "visual_evidence_available": visual_available,
        "image_detail": image_detail,
        "region_detail": crop_detail,
        "rejection_reasons": reasons,
    }


def _cluster_identity(member_ids: list[str]) -> str:
    canonical = json.dumps(sorted(member_ids), separators=(",", ":"))
    return "issue-cluster-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _evidence_entry(issue: dict[str, Any]) -> dict[str, Any]:
    evidence = issue.get("evidence") if isinstance(issue.get("evidence"), dict) else {}
    return {
        "source_issue_id": issue.get("issue_id"),
        "timestamp": round(float(issue.get("timestamp") or 0.0), 3),
        "frame_index": evidence.get("frame_index", issue.get("evidence_frame_index")),
        "scene_index": evidence.get("scene_index"),
        "s3_key": evidence.get("s3_key"),
        "bbox": dict(issue.get("bbox") or {}),
        "confidence": float(issue.get("confidence") or 0.0),
        "description": issue.get("description"),
    }


def _consolidated_issue(cluster: dict[str, Any]) -> dict[str, Any]:
    members = sorted(
        cluster["members"],
        key=lambda item: (float(item.get("timestamp") or 0.0), str(item.get("issue_id") or "")),
    )
    representative = min(
        members,
        key=lambda item: (-float(item.get("confidence") or 0.0), float(item.get("timestamp") or 0.0)),
    )
    result = dict(representative)
    member_ids = [str(item.get("issue_id") or "") for item in members]
    evidence = [_evidence_entry(item) for item in members]
    result["issue_id"] = representative.get("issue_id") if len(members) == 1 else _cluster_identity(member_ids)
    result["representative_issue_id"] = representative.get("issue_id")
    result["source_issue_ids"] = member_ids
    result["consolidated_from_count"] = len(members)
    result["evidence_timestamps"] = [item["timestamp"] for item in evidence]
    result["supporting_frame_indices"] = [
        item["frame_index"] for item in evidence if item.get("frame_index") is not None
    ]
    result["supporting_evidence"] = evidence
    result["consolidation"] = {
        "version": CONSOLIDATION_VERSION,
        "representative_selection": "highest_confidence_then_earliest_timestamp",
        "pairwise_matches": cluster["matches"],
    }
    return result


def consolidate_issues(
    issues: list[dict[str, Any]],
    *,
    image_loader: ImageLoader | None = None,
    config: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Conservatively merge repeated frame-level observations of the same physical issue."""
    resolved = {**DEFAULT_CONFIG, **(config or {})}
    ordered = sorted(
        (dict(issue) for issue in issues),
        key=lambda item: (float(item.get("timestamp") or 0.0), str(item.get("issue_id") or "")),
    )
    clusters: list[dict[str, Any]] = []
    image_cache: dict[str, np.ndarray | None] = {}
    comparisons: list[dict[str, Any]] = []

    for issue in ordered:
        best: tuple[float, int, dict[str, Any]] | None = None
        for cluster_index, cluster in enumerate(clusters):
            timestamps = [float(member.get("timestamp") or 0.0) for member in cluster["members"]]
            expanded_span = max(timestamps + [float(issue.get("timestamp") or 0.0)]) - min(
                timestamps + [float(issue.get("timestamp") or 0.0)]
            )
            if expanded_span > resolved["max_cluster_span_seconds"]:
                continue
            for member in cluster["members"]:
                comparison = compare_issues(
                    member,
                    issue,
                    image_loader=image_loader,
                    image_cache=image_cache,
                    config=resolved,
                )
                comparisons.append(comparison)
                if comparison["merge"] and (best is None or comparison["score"] > best[0]):
                    best = (comparison["score"], cluster_index, comparison)
        if best is None:
            clusters.append({"members": [issue], "matches": []})
        else:
            _, cluster_index, comparison = best
            clusters[cluster_index]["members"].append(issue)
            clusters[cluster_index]["matches"].append(comparison)

    consolidated = [_consolidated_issue(cluster) for cluster in clusters]
    visual_comparisons = sum(1 for item in comparisons if item["visual_evidence_available"])
    return {
        "version": CONSOLIDATION_VERSION,
        "raw_issue_count": len(ordered),
        "consolidated_issue_count": len(consolidated),
        "duplicate_observations_merged": len(ordered) - len(consolidated),
        "visual_comparison_count": visual_comparisons,
        "metadata_only_comparison_count": len(comparisons) - visual_comparisons,
        "config": resolved,
        "signal_weights": dict(SIGNAL_WEIGHTS),
        "issues": consolidated,
        "comparisons": comparisons,
    }
