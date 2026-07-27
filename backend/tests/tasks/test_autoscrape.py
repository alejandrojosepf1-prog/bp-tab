"""The in-process periodic scraper's resilience contract: one tournament blowing up must never
stop the others, and must never kill the loop (which would silently freeze all auto-updating for
the rest of the process's uptime -- exactly the failure mode that's hardest to notice in prod)."""

import asyncio

import pytest

from app.tasks import autoscrape


async def test_run_one_cycle_scrapes_every_active_tournament(monkeypatch) -> None:
    scraped = []

    async def fake_list():
        return [1, 2, 3]

    async def fake_scrape(tournament_id):
        scraped.append(tournament_id)
        return {"tournament_id": tournament_id}

    monkeypatch.setattr(autoscrape, "scrape_all_active_tournaments_async", fake_list)
    monkeypatch.setattr(autoscrape, "scrape_tournament_async", fake_scrape)

    await autoscrape._run_one_cycle()

    assert scraped == [1, 2, 3]


async def test_run_one_cycle_continues_after_a_tournament_fails(monkeypatch) -> None:
    scraped = []

    async def fake_list():
        return [1, 2, 3]

    async def fake_scrape(tournament_id):
        if tournament_id == 2:
            raise RuntimeError("upstream tab returned a 500")
        scraped.append(tournament_id)
        return {}

    monkeypatch.setattr(autoscrape, "scrape_all_active_tournaments_async", fake_list)
    monkeypatch.setattr(autoscrape, "scrape_tournament_async", fake_scrape)

    await autoscrape._run_one_cycle()  # must not raise

    assert scraped == [1, 3]  # tournament 3 still ran after 2 blew up


async def test_loop_survives_a_failing_cycle_and_keeps_going(monkeypatch) -> None:
    cycles = 0

    async def fake_cycle():
        nonlocal cycles
        cycles += 1
        if cycles == 1:
            raise RuntimeError("database unreachable this cycle")

    monkeypatch.setattr(autoscrape, "_run_one_cycle", fake_cycle)
    settings = autoscrape.get_settings()
    monkeypatch.setattr(settings, "autoscrape_startup_delay_seconds", 0)
    monkeypatch.setattr(settings, "scrape_interval_seconds", 0)

    task = asyncio.create_task(autoscrape.autoscrape_loop())
    # Yield enough times for several cycles to run at a zero-second interval.
    for _ in range(20):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert cycles > 1  # the RuntimeError on cycle 1 did not end the loop


async def test_loop_stops_cleanly_on_cancel(monkeypatch) -> None:
    async def fake_cycle():
        return None

    monkeypatch.setattr(autoscrape, "_run_one_cycle", fake_cycle)
    settings = autoscrape.get_settings()
    monkeypatch.setattr(settings, "autoscrape_startup_delay_seconds", 0)
    monkeypatch.setattr(settings, "scrape_interval_seconds", 60)

    task = asyncio.create_task(autoscrape.autoscrape_loop())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
