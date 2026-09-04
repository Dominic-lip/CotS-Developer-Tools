#!/usr/bin/env python3
"""Stable production entry point for the CotS Development Control Center.

This wrapper keeps the production Control Center behaviour but fixes an operator
usability bug: the one-second telemetry refresh must not steal the Recent
Activity scroll position while the operator is reading older entries.
"""
from __future__ import annotations

from typing import Any
from tkinter import ttk

from CotSControlCenter24x7Final import ProductionControlCenter


class StableProductionControlCenter(ProductionControlCenter):
    """Production Control Center with non-destructive activity refreshes."""

    def __init__(self) -> None:
        super().__init__()
        self.title("CotS Development Control Center v3.1.3")

        # Make the activity pane explicitly scrollable. Mouse-wheel scrolling
        # already works on the Text widget, but a visible scrollbar also makes
        # the current position obvious during long autonomous sessions.
        activity_parent = self.activity_text.master
        activity_parent.columnconfigure(1, weight=0)
        self.activity_scrollbar = ttk.Scrollbar(
            activity_parent,
            orient="vertical",
            command=self.activity_text.yview,
        )
        self.activity_scrollbar.grid(row=1, column=1, sticky="ns")
        self.activity_text.configure(yscrollcommand=self.activity_scrollbar.set)

    def _refresh_overview(
        self,
        health: dict[str, Any],
        supervisor: dict[str, Any],
        usage: dict[str, Any],
        governor: dict[str, Any],
        report: dict[str, Any],
    ) -> None:
        """Refresh telemetry without yanking Recent Activity from the reader.

        The inherited refresh rewrites the Text widget whenever the telemetry
        tail changes and then calls ``see('end')``. That is correct while the
        operator is following live output, but it makes historical inspection
        impossible because every one-second refresh jumps the viewport.

        Follow new activity only when the operator was already at the bottom;
        otherwise restore the pre-refresh viewport.
        """
        view_before = self.activity_text.yview()
        was_following_live = not view_before or view_before[1] >= 0.995

        super()._refresh_overview(health, supervisor, usage, governor, report)

        if not was_following_live and view_before:
            self.activity_text.yview_moveto(view_before[0])


if __name__ == "__main__":
    StableProductionControlCenter().mainloop()
