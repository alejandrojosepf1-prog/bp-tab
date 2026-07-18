class ScraperError(Exception):
    """Base class for every error raised by the scraper package."""


class PageNotAvailableError(ScraperError):
    """The page returned 403/404. This means the organizer hasn't published that data yet
    (e.g. a draw before results are released) -- callers should treat this as 'no data yet',
    never as a fatal scrape failure."""

    def __init__(self, url: str, status_code: int) -> None:
        self.url = url
        self.status_code = status_code
        super().__init__(f"{url} returned {status_code} (not published yet)")


class ParseError(ScraperError):
    """The page was fetched successfully but its structure didn't match what we expect.
    Raised with enough context to tell whether Tabbycat changed its template."""

    def __init__(self, message: str, *, url: str | None = None) -> None:
        self.url = url
        full = f"{message} (url={url})" if url else message
        super().__init__(full)
