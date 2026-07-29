"""Motivation Reels services.

Quote-driven vertical-video pipeline. Stage logic lives here as plain async
functions/services so it's directly testable and runnable without the Temporal
worker; ``app.workflows.activities.reels`` wraps these as thin activities and
``app.workflows.reel_workflow`` orchestrates them durably.
"""
