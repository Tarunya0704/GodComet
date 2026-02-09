"""
Confidence Scorer - Calculates visual similarity metrics
Combines multiple algorithms for accurate scoring
"""

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim
from typing import Dict, Tuple, Optional


class ConfidenceScorer:
    """
    Calculates confidence scores for visual similarity
    Uses multiple metrics for robust scoring
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None
    ):
        """
        Initialize Confidence Scorer

        Args:
            weights: Custom weights for different metrics
                     Default: {"ssim": 0.3, "pixel": 0.3, "vision": 0.4}
        """
        self.weights = weights or {
            "ssim": 0.30,      # Structural similarity
            "pixel": 0.30,     # Pixel-wise difference
            "vision": 0.40     # Vision LLM semantic score
        }

    def calculate_overall_score(
        self,
        structural_score: float,
        pixel_score: float,
        vision_score: float
    ) -> float:
        """
        Calculate weighted overall confidence score

        Returns:
            Float between 0.0 and 1.0
        """
        # If no vision score, redistribute weight
        if vision_score == 0.0:
            return (
                structural_score * 0.50 +
                pixel_score * 0.50
            )

        # With vision score, use full weights
        return (
            structural_score * self.weights["ssim"] +
            pixel_score * self.weights["pixel"] +
            vision_score * self.weights["vision"]
        )

    def calculate_ssim(
        self,
        img1_path: str,
        img2_path: str
    ) -> float:
        """
        Calculate Structural Similarity Index (SSIM)

        Returns:
            Float between -1.0 and 1.0 (typically 0.0 to 1.0)
        """
        try:
            img1 = np.array(Image.open(img1_path).convert("RGB"))
            img2 = np.array(Image.open(img2_path).convert("RGB"))

            # Resize if needed
            if img1.shape != img2.shape:
                img2_pil = Image.fromarray(img2)
                img2_pil = img2_pil.resize(
                    (img1.shape[1], img1.shape[0]),
                    Image.Resampling.LANCZOS
                )
                img2 = np.array(img2_pil)

            # Convert to grayscale for SSIM
            from skimage.color import rgb2gray
            gray1 = rgb2gray(img1)
            gray2 = rgb2gray(img2)

            score = ssim(
                gray1,
                gray2,
                data_range=gray1.max() - gray1.min()
            )

            return float(score)

        except Exception as e:
            print(f"⚠️  SSIM calculation failed: {e}")
            return 0.0

    def calculate_pixel_similarity(
        self,
        img1_path: str,
        img2_path: str
    ) -> float:
        """
        Calculate pixel-wise similarity (inverse of normalized difference)

        Returns:
            Float between 0.0 and 1.0
        """
        try:
            img1 = np.array(Image.open(img1_path).convert("RGB"))
            img2 = np.array(Image.open(img2_path).convert("RGB"))

            # Resize if needed
            if img1.shape != img2.shape:
                img2_pil = Image.fromarray(img2)
                img2_pil = img2_pil.resize(
                    (img1.shape[1], img1.shape[0]),
                    Image.Resampling.LANCZOS
                )
                img2 = np.array(img2_pil)

            # Calculate normalized difference
            diff = np.abs(img1.astype(float) - img2.astype(float))
            total_diff = np.sum(diff)
            max_diff = img1.size * 255  # Maximum possible difference

            similarity = 1.0 - (total_diff / max_diff)
            return float(similarity)

        except Exception as e:
            print(f"⚠️  Pixel similarity calculation failed: {e}")
            return 0.0

    def calculate_color_accuracy(
        self,
        img1_path: str,
        img2_path: str,
        tolerance: int = 5
    ) -> Dict:
        """
        Calculate color accuracy with tolerance

        Args:
            tolerance: Acceptable difference in RGB values (0-255)

        Returns:
            {
                "score": 0.95,
                "within_tolerance": 0.98,
                "exact_match": 0.87,
                "max_color_diff": 15
            }
        """
        try:
            img1 = np.array(Image.open(img1_path).convert("RGB"))
            img2 = np.array(Image.open(img2_path).convert("RGB"))

            # Resize if needed
            if img1.shape != img2.shape:
                img2_pil = Image.fromarray(img2)
                img2_pil = img2_pil.resize(
                    (img1.shape[1], img1.shape[0]),
                    Image.Resampling.LANCZOS
                )
                img2 = np.array(img2_pil)

            # Calculate per-pixel color difference
            diff = np.abs(img1.astype(float) - img2.astype(float))

            # Max difference per pixel (across RGB channels)
            max_diff_per_pixel = np.max(diff, axis=2)

            # Calculate metrics
            total_pixels = img1.shape[0] * img1.shape[1]
            exact_match = np.sum(max_diff_per_pixel == 0) / total_pixels
            within_tolerance = np.sum(max_diff_per_pixel <= tolerance) / total_pixels
            max_color_diff = np.max(max_diff_per_pixel)

            # Overall color score (weighted towards tolerance)
            score = (exact_match * 0.4 + within_tolerance * 0.6)

            return {
                "score": float(score),
                "within_tolerance": float(within_tolerance),
                "exact_match": float(exact_match),
                "max_color_diff": float(max_color_diff),
                "tolerance": tolerance
            }

        except Exception as e:
            print(f"⚠️  Color accuracy calculation failed: {e}")
            return {
                "score": 0.0,
                "within_tolerance": 0.0,
                "exact_match": 0.0,
                "max_color_diff": 255,
                "tolerance": tolerance
            }

    def calculate_layout_score(
        self,
        img1_path: str,
        img2_path: str
    ) -> Dict:
        """
        Calculate layout similarity using edge detection

        Returns:
            {
                "score": 0.93,
                "edge_similarity": 0.91,
                "structure_match": 0.95
            }
        """
        try:
            from skimage import filters, color

            img1 = np.array(Image.open(img1_path).convert("RGB"))
            img2 = np.array(Image.open(img2_path).convert("RGB"))

            # Resize if needed
            if img1.shape != img2.shape:
                img2_pil = Image.fromarray(img2)
                img2_pil = img2_pil.resize(
                    (img1.shape[1], img1.shape[0]),
                    Image.Resampling.LANCZOS
                )
                img2 = np.array(img2_pil)

            # Convert to grayscale
            gray1 = color.rgb2gray(img1)
            gray2 = color.rgb2gray(img2)

            # Apply Sobel edge detection
            edges1 = filters.sobel(gray1)
            edges2 = filters.sobel(gray2)

            # Calculate edge similarity
            edge_diff = np.abs(edges1 - edges2)
            edge_similarity = 1.0 - (np.sum(edge_diff) / np.sum(edges1 + edges2 + 1e-10))

            # Calculate structural match using SSIM on edges
            structure_match = ssim(edges1, edges2, data_range=edges1.max() - edges1.min())

            score = (edge_similarity * 0.5 + structure_match * 0.5)

            return {
                "score": float(score),
                "edge_similarity": float(edge_similarity),
                "structure_match": float(structure_match)
            }

        except Exception as e:
            print(f"⚠️  Layout score calculation failed: {e}")
            return {
                "score": 0.0,
                "edge_similarity": 0.0,
                "structure_match": 0.0
            }

    def get_comprehensive_metrics(
        self,
        img1_path: str,
        img2_path: str
    ) -> Dict:
        """
        Get all available metrics in one call

        Returns:
            {
                "overall_score": 0.94,
                "ssim": 0.92,
                "pixel_similarity": 0.95,
                "color_accuracy": {...},
                "layout_score": {...}
            }
        """
        print(f"📊 Calculating comprehensive metrics...")

        ssim_score = self.calculate_ssim(img1_path, img2_path)
        pixel_score = self.calculate_pixel_similarity(img1_path, img2_path)
        color_metrics = self.calculate_color_accuracy(img1_path, img2_path)
        layout_metrics = self.calculate_layout_score(img1_path, img2_path)

        # Calculate overall (without vision score)
        overall = self.calculate_overall_score(ssim_score, pixel_score, 0.0)

        return {
            "overall_score": overall,
            "ssim": ssim_score,
            "pixel_similarity": pixel_score,
            "color_accuracy": color_metrics,
            "layout_score": layout_metrics,
            "weights": self.weights
        }

    def interpret_score(self, score: float) -> Dict:
        """
        Interpret the confidence score and provide recommendations

        Returns:
            {
                "grade": "A" | "B" | "C" | "D" | "F",
                "action": "deploy" | "self_heal" | "human_review",
                "message": "..."
            }
        """
        if score >= 0.95:
            return {
                "grade": "A",
                "action": "deploy",
                "message": "Excellent match! Safe to auto-deploy.",
                "color": "green"
            }
        elif score >= 0.90:
            return {
                "grade": "B",
                "action": "deploy",
                "message": "Very good match. Minor differences acceptable.",
                "color": "lightgreen"
            }
        elif score >= 0.85:
            return {
                "grade": "C",
                "action": "self_heal",
                "message": "Good match but needs improvement. Try self-healing.",
                "color": "yellow"
            }
        elif score >= 0.75:
            return {
                "grade": "D",
                "action": "self_heal",
                "message": "Significant differences. Self-healing required.",
                "color": "orange"
            }
        else:
            return {
                "grade": "F",
                "action": "human_review",
                "message": "Major discrepancies. Human review needed.",
                "color": "red"
            }


# Standalone test
def test_confidence_scorer():
    """Test the confidence scorer with sample images"""
    print("🧪 Testing Confidence Scorer\n")

    # Create test images
    from pathlib import Path
    test_dir = Path("test_scorer")
    test_dir.mkdir(exist_ok=True)

    # Create two similar images
    img1 = Image.new("RGB", (800, 600), color=(255, 0, 0))
    img2 = Image.new("RGB", (800, 600), color=(250, 5, 5))  # Slightly different

    img1_path = test_dir / "reference.png"
    img2_path = test_dir / "candidate.png"

    img1.save(img1_path)
    img2.save(img2_path)

    # Test scorer
    scorer = ConfidenceScorer()

    print("📊 Calculating metrics...")
    metrics = scorer.get_comprehensive_metrics(str(img1_path), str(img2_path))

    print("\n📈 Results:")
    print(f"Overall Score: {metrics['overall_score']:.2%}")
    print(f"SSIM: {metrics['ssim']:.2%}")
    print(f"Pixel Similarity: {metrics['pixel_similarity']:.2%}")
    print(f"Color Accuracy: {metrics['color_accuracy']['score']:.2%}")
    print(f"Layout Score: {metrics['layout_score']['score']:.2%}")

    interpretation = scorer.interpret_score(metrics['overall_score'])
    print(f"\n{interpretation['grade']} Grade: {interpretation['message']}")
    print(f"Recommended Action: {interpretation['action']}")


if __name__ == "__main__":
    test_confidence_scorer()
