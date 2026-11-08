from apps.worker.app import main


def test_worker_cycle_analyzes_before_delivery(monkeypatch) -> None:
    calls: list[tuple[str, int | None]] = []

    monkeypatch.setattr(
        main,
        "poll_due_projects",
        lambda engine, worker_name: calls.append(("poll", None)) or 1,
    )
    monkeypatch.setattr(
        main,
        "analyze_pending_events",
        lambda engine, limit, worker_name: calls.append(("analyze", limit)) or 1,
    )
    monkeypatch.setattr(
        main,
        "deliver_due_notifications",
        lambda engine, worker_name: calls.append(("deliver", None)) or 1,
    )

    main.run_cycle()

    assert calls == [("poll", None), ("analyze", 20), ("deliver", None)]
