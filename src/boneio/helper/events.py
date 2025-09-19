import asyncio
import datetime as dt
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

_LOGGER = logging.getLogger(__name__)
UTC = dt.timezone.utc
EVENT_TIME_CHANGED = "event_time_changed"
CALLBACK_TYPE = Callable[[], None]


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC)


time_tracker_utcnow = utcnow


def _async_create_timer(
    loop: asyncio.AbstractEventLoop, event_callback: Callable[[dt.datetime], None]
) -> Callable[[], None]:
    """Create a timer that will start on BoneIO start."""
    handle = None

    def schedule_tick(now: dt.datetime) -> None:
        """Schedule a timer tick when the next second rolls around."""
        nonlocal handle
        slp_seconds = 1 - (now.microsecond / 10**6)
        handle = loop.call_later(slp_seconds, fire_time_event)

    def fire_time_event() -> None:
        """Fire next time event."""
        now = utcnow()
        event_callback()
        schedule_tick(now)

    def stop_timer() -> None:
        """Stop the timer."""
        if handle is not None:
            handle.cancel()

    schedule_tick(utcnow())
    return stop_timer


class ListenerJob:
    """Listener to represent jobs during runtime."""

    def __init__(self, target: Callable) -> None:
        """Initialize listener."""
        self.target = target
        self.handle = None

    def add_handle(self, handle: Any) -> None:
        """Add handle to listener."""
        self.handle = handle

    def set_target(self, target: Callable) -> None:
        """Set target."""
        self.target = target


class EventBus:
    """
    Simple event bus with async queue for multiple event types.
    Obsługuje wiele typów eventów oraz asynchroniczne kolejkowanie i dispatching.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """
        Initialize the event bus.
        :param loop: asyncio event loop
        """
        if loop is None:
            loop = asyncio.get_event_loop()
        self._loop = loop
        self._event_queue = asyncio.Queue()
        self._event_listeners: dict[str, dict[str, dict[str, ListenerJob]]] = {
            "input": {},
            "output": {},
            "cover": {},
            "modbus_device": {},
            "sensor": {},
            "host": {},
        }
        self._listener_id_index: dict[str, list[tuple[str, str]]] = {}
        self._worker_task: asyncio.Task | None = None
        self._every_second_listeners: dict[str, ListenerJob] = {}
        self._shutting_down = False
        self._sigterm_listeners: list[Callable] = []
        self._haonline_listeners: list[Callable[[], None]] = []
        self._timer_handle = _async_create_timer(self._loop, self._run_second_event)
        self._shutting_down = False
        self._monitor_task = None

    async def start(self) -> None:
        """
        Start the event bus worker.
        """
        if self._worker_task is not None:
            _LOGGER.warning("Event bus worker already started.")
            return
        self._worker_task = asyncio.create_task(self._event_worker())
        _LOGGER.info("Event bus worker started.")

    async def _event_worker(self) -> None:
        """
        Background task to process events from the queue.
        """
        while not self._shutting_down:
            try:
                event = await self._event_queue.get()
            except asyncio.CancelledError:
                _LOGGER.info("Event bus worker cancelled.")
                await self.stop()
                raise
            try:
                await self._handle_event(event)
            except Exception as exc:
                _LOGGER.error("Error handling event: %s", exc)
            finally:
                self._event_queue.task_done()

    async def _handle_event(self, event: dict[str, Any]) -> None:
        """
        Dispatch event to registered listeners.
        :param event: dict or object with at least 'event_type' field
        """
        event_type = event.get("event_type")
        event_state = event.get("event_state")
        entity_id = event.get("entity_id")
        if not event_type or event_type not in self._event_listeners:
            _LOGGER.warning("Unknown event_type: %s", event_type)
            return
        if not entity_id:
            _LOGGER.warning("Unknown entity_id: %s", entity_id)
            return
        entity_id_listeners = self._event_listeners.get(event_type, {}).get(
            entity_id, {}
        )
        for listener in entity_id_listeners.values():
            try:
                await listener.target(event_state)
            except Exception as exc:
                _LOGGER.error("Listener error: %s", exc)

    def trigger_event(self, event: dict[str, Any]) -> None:
        """
        Put event into the queue for async processing.
        :param event: dict or object with at least 'event_type' field
        """
        self._event_queue.put_nowait(event)

    def request_stop(self) -> None:
        """Request the event bus to stop."""
        if self._worker_task and not self._shutting_down:
            self._shutting_down = True
            self._worker_task.cancel()

    async def stop(self) -> None:
        """
        Stop the event bus and worker task gracefully.
        """
        if self._shutting_down:
            return
        self._shutting_down = True
        await self._handle_sigterm_listeners()
        for listener in self._every_second_listeners.values():
            listener.target(None)
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                _LOGGER.info("Event bus worker cancelled.")
        _LOGGER.info("Shutdown EventBus gracefully.")

    def _run_second_event(self) -> None:
        """Run event every second."""
        for key, listener in self._every_second_listeners.items():
            if listener.target:
                self._every_second_listeners[key].add_handle(
                    self._loop.call_soon(listener.target)
                )

    def _timer_handle(self) -> None:
        """Handle timer event."""
        for listener in self._every_second_listeners.values():
            self._loop.call_soon(listener.target)

    async def _handle_sigterm_listeners(self) -> None:
        """Handle all sigterm listeners, supporting both async and sync listeners."""
        for target in self._sigterm_listeners:
            try:
                _LOGGER.debug("Invoking sigterm listener %s", target)
                if asyncio.iscoroutinefunction(target):
                    await target()
                else:
                    target()
            except Exception as e:
                _LOGGER.error("Error in sigterm listener %s: %s", target, e)

    def ask_exit(self) -> None:
        """Function to call on exit. Should invoke all sigterm listeners."""
        if self._shutting_down:
            return
        self._shutting_down = True
        _LOGGER.debug("EventBus Exiting process started.")

        def task_done_callback(task) -> None:
            task.result()  # Retrieve the result to handle any raised exception
            raise asyncio.CancelledError

        async def cleanup_and_exit() -> None:
            try:
                await asyncio.sleep(2)
                await self.ask_stop()
            except Exception as e:
                _LOGGER.error("Error during cleanup: %s", e)

        # Create and run the cleanup task
        exit_task = self._loop.create_task(cleanup_and_exit())
        exit_task.add_done_callback(task_done_callback)

    def add_every_second_listener(self, name, target):
        """Add listener on every second job."""
        self._every_second_listeners[name] = ListenerJob(target=target)
        return self._every_second_listeners[name]

    def add_sigterm_listener(self, target: Callable) -> None:
        """Add sigterm listener."""
        self._sigterm_listeners.append(target)

    def add_event_listener(
        self, event_type: str, entity_id: str, listener_id: str, target: Callable
    ) -> ListenerJob | None:
        """Add event listener.

        listener_id is typically group_id for group outputs or ws (websocket)
        """
        if not target:
            return None
        if entity_id not in self._event_listeners[event_type]:
            self._event_listeners[event_type][entity_id] = {}
        if listener_id in self._event_listeners[event_type][entity_id]:
            listener = self._event_listeners[event_type][entity_id][listener_id]
            listener.set_target(target)
            return listener

        # Add to main listeners
        listener_job = ListenerJob(target=target)
        self._event_listeners[event_type][entity_id][listener_id] = listener_job

        # Add to index
        if listener_id not in self._listener_id_index:
            self._listener_id_index[listener_id] = []
        self._listener_id_index[listener_id].append((event_type, entity_id))

        return listener_job

    def remove_event_listener(
        self,
        event_type: str | None = None,
        entity_id: str | None = None,
        listener_id: str | None = None,
    ) -> None:
        """Remove event listener. Can remove by event_type, listener_id, or both."""
        if listener_id and listener_id in self._listener_id_index:
            # Remove by listener_id
            for evt_type, ent_id in self._listener_id_index[listener_id]:
                if event_type and evt_type != event_type:
                    continue
                if entity_id and ent_id != entity_id:
                    continue
                if ent_id in self._event_listeners[evt_type]:
                    if listener_id in self._event_listeners[evt_type][ent_id]:
                        del self._event_listeners[evt_type][ent_id][listener_id]
                    if not self._event_listeners[evt_type][ent_id]:
                        del self._event_listeners[evt_type][ent_id]

            if event_type is None and entity_id is None:
                # If removing all references to this listener_id
                del self._listener_id_index[listener_id]
            else:
                # Update index to remove only specific references
                self._listener_id_index[listener_id] = [
                    (evt_type, ent_id)
                    for evt_type, ent_id in self._listener_id_index[listener_id]
                    if (event_type and evt_type != event_type)
                    or (entity_id and ent_id != entity_id)
                ]
                if not self._listener_id_index[listener_id]:
                    del self._listener_id_index[listener_id]

        elif event_type:
            # Remove by event_type
            if entity_id:
                # Remove specific entity
                if entity_id in self._event_listeners[event_type]:
                    for lid in list(
                        self._event_listeners[event_type][entity_id].keys()
                    ):
                        self.remove_event_listener(event_type, entity_id, lid)
                    del self._event_listeners[event_type][entity_id]
            else:
                # Remove entire event_type
                for ent_id in list(self._event_listeners[event_type].keys()):
                    for lid in list(self._event_listeners[event_type][ent_id].keys()):
                        self.remove_event_listener(event_type, ent_id, lid)

    def add_haonline_listener(self, target: Callable[[], None]) -> None:
        """Add HA Online listener."""
        self._haonline_listeners.append(target)

    def signal_ha_online(self) -> None:
        """Call events if HA goes online."""
        for target in self._haonline_listeners:
            target()

    def remove_every_second_listener(self, name: str) -> None:
        """Remove regular listener."""
        if name in self._every_second_listeners:
            del self._every_second_listeners[name]


def _as_utc(dattim: dt.datetime) -> dt.datetime:
    """Return a datetime as UTC time.

    Assumes datetime without tzinfo to be in the DEFAULT_TIME_ZONE.
    """
    if dattim.tzinfo == UTC:
        return dattim
    return dattim.astimezone(UTC)


def async_track_point_in_time(
    loop: asyncio.AbstractEventLoop, job, point_in_time: datetime, **kwargs
) -> Callable[[], None]:
    """Add a listener that fires once after a specific point in UTC time."""
    # Ensure point_in_time is UTC
    utc_point_in_time = _as_utc(point_in_time)
    expected_fire_timestamp = utc_point_in_time.timestamp()

    # Since this is called once, we accept a so we can avoid
    # having to figure out how to call the action every time its called.
    cancel_callback: asyncio.TimerHandle | None = None

    def run_action(job) -> None:
        """Call the action."""
        nonlocal cancel_callback

        # Depending on the available clock support (including timer hardware
        # and the OS kernel) it can happen that we fire a little bit too early
        # as measured by utcnow(). That is bad when callbacks have assumptions
        # about the current time. Thus, we rearm the timer for the remaining
        # time.
        delta = expected_fire_timestamp - time.time()
        if delta > 0:
            _LOGGER.debug("Called %f seconds too early, rearming", delta)

            cancel_callback = loop.call_later(delta, run_action, job)
            return

        if asyncio.iscoroutinefunction(job):
            loop.create_task(job(utc_point_in_time, **kwargs))
        else:
            loop.call_soon(job, utc_point_in_time, **kwargs)

    delta = expected_fire_timestamp - time.time()
    cancel_callback = loop.call_later(delta, run_action, job)

    def unsub_point_in_time_listener() -> None:
        """Cancel the call_later."""
        assert cancel_callback is not None
        cancel_callback.cancel()

    return unsub_point_in_time_listener
