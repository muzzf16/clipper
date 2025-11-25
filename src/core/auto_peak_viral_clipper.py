"""
Auto Peak Viral Clipper - Compatibility wrapper
This module provides backward compatibility by aliasing ViralClipGenerator
"""
from .viral_clipper_complete import ViralClipGenerator as AutoPeakViralClipper

__all__ = ['AutoPeakViralClipper']