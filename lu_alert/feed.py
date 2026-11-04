"""Which alert files to read, what is cached, concurrent downloads. Knows neither Domoticz nor the details of HTTP.

The dataset has one file per CAP message and its description lists them all. A file never changes once it is
published (a change of an alert is a new message), so a file is downloaded once and kept in memory under its URL and
its last-modified stamp. A poll therefore costs one request for the description plus one per *new* file; only the
first poll after a start reads up to ``max_resources`` files. The work runs in the background thread of the
controller, so nothing here may call Domoticz: messages for the log are returned with the result.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

from .api import DATA, TOO_LARGE, ApiError, Client, Resource
from .cap import CapError, parse_cap
from .constants import FETCH_WORKERS
from .model import CapAlert


class FeedResult(NamedTuple):
    cap_alerts: List[CapAlert]
    listed: int                         # alert files within the limit
    fetched: int                        # downloaded in this refresh
    cached: int                         # taken from the cache
    failed: int                         # not readable right now (network, HTTP): tried again at the next poll
    unreadable: int                     # not CAP or too large: not tried again for this version of the file
    errors: List[str]                   # a few examples of what went wrong
    messages: List[Tuple[str, str]]     # (level, text) for the log: written by the controller on the main thread


class Feed:
    def __init__(self, client: Client, max_resources: int, workers: int = FETCH_WORKERS) -> None:
        self.client = client
        self.max_resources = max_resources
        self.workers = workers
        # url -> (version, alerts or None when the file is not readable for good)
        self._cache: Dict[str, Tuple[str, Optional[List[CapAlert]]]] = {}

    def refresh(self, should_stop: Callable[[], bool] = lambda: False) -> FeedResult:
        """Read the dataset description and the new files. Raises ApiError when the description cannot be read."""
        messages: List[Tuple[str, str]] = []
        resources = self.client.list_resources(self.max_resources)
        todo = []
        for resource in resources:
            entry = self._cache.get(resource.url)
            if entry is None or entry[0] != resource.modified:
                todo.append(resource)
        for url in set(self._cache) - {r.url for r in resources}:
            del self._cache[url]                                # a file that dropped out of the list: forget it
        messages.append(("basic", "The dataset lists %d alert files (limit %d): %d to read, %d cached"
                         % (len(resources), self.max_resources, len(todo), len(resources) - len(todo))))

        fetched, failed, errors = 0, 0, []
        for resource, outcome in self._download(todo, should_stop):
            if isinstance(outcome, ApiError) and outcome.kind not in (DATA, TOO_LARGE):
                failed += 1                                     # the network or the server: try again at the next poll
                errors.append("%s: %s" % (resource.url, outcome))
                messages.append(("verbose", "Could not read %s: %s" % (resource.url, outcome)))
            elif isinstance(outcome, (ApiError, CapError)):
                self._cache[resource.url] = (resource.modified, None)   # this version of the file will never be readable
                errors.append("%s: %s" % (resource.url, outcome))
                messages.append(("verbose", "Unreadable alert file %s: %s" % (resource.url, outcome)))
            else:
                fetched += 1
                self._cache[resource.url] = (resource.modified, outcome)
                messages.append(("debug", "Read %s: %d message(s)" % (resource.url, len(outcome))))

        alerts: List[CapAlert] = []
        unreadable = 0
        for resource in resources:
            entry = self._cache.get(resource.url)
            if entry is None:
                continue
            if entry[1] is None:
                unreadable += 1                                 # counted at every poll, so a report does not blink
            else:
                alerts.extend(entry[1])
        return FeedResult(alerts, len(resources), fetched, len(resources) - len(todo), failed, unreadable, errors[:3],
                          messages)

    def _download(self, todo: List[Resource], should_stop: Callable[[], bool]):
        """Yield (resource, list of CapAlert | exception) as the files arrive; stop early when asked to."""
        if not todo:
            return
        executor = ThreadPoolExecutor(max_workers=max(1, min(self.workers, len(todo))))
        try:
            futures = {executor.submit(self._read_one, r): r for r in todo}
            for future in as_completed(futures):
                if should_stop():
                    break
                yield futures[future], future.result()
        finally:
            for future in futures:
                future.cancel()
            executor.shutdown(wait=False)

    def _read_one(self, resource: Resource):
        """The messages of one file, or the exception that says why not (never raises)."""
        try:
            return parse_cap(self.client.get_xml(resource.url))
        except (ApiError, CapError) as exc:
            return exc
        except Exception as exc:                                # a parser bug must not take the poll down
            return CapError("%s: %s" % (type(exc).__name__, exc))
