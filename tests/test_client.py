"""Exercise complete jobs against an emulated BLE transport, not real paper."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bleak.exc import BleakError
from PIL import Image
import pytest

from funprint import cli, client
from funprint.client import AsyncFunPrinter, FunPrintConnectionError, FunPrintJobError
from funprint.protocol import Command, DATA_CHAR_UUID, NOTIFY_CHAR_UUID, NotificationParser, crc8, make_command


def response(command, payload):
    # Captured firmware format: header + payload + a single zero tail byte.
    return b"\x22\x21" + bytes([command, 0]) + len(payload).to_bytes(2, "little") + payload + b"\x00"


class EmulatedBLE:
    def __init__(self, device, timeout, disconnected_callback):
        self.is_connected = False
        self.disconnected_callback = disconnected_callback
        self.callback = None
        self.services = SimpleNamespace(get_characteristic=lambda uuid: SimpleNamespace(max_write_without_response_size=20))
        self.raster = bytearray()
        self.completions = 0
        self.requests = 0
        self.status_requests = 0
        self.densities = []
        self.chunks = []
        self.paper_missing = False
        self.accept = 0
        self.bad_checksum = False
        self.skip_completion = None
        self.complete_before_flush = False
        self.busy_after_completion = False
        self._busy = False
        self.events = []

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False
        self.disconnected_callback(self)

    async def start_notify(self, uuid, callback):
        assert uuid == NOTIFY_CHAR_UUID
        self.callback = callback
        self.events.append("subscribed")

    def notify(self, command, payload):
        frame = response(command, payload)
        # Split the header/payload and concatenate a footer across notifications.
        self.callback(None, frame[:1])
        self.callback(None, frame[1:5])
        self.callback(None, frame[5:])

    def complete(self):
        self.completions += 1
        if self.skip_completion == self.requests:
            return
        checksum = crc8(self.raster) ^ int(self.bad_checksum)
        self.notify(Command.PRINT_COMPLETE, bytes([0, checksum, checksum]))
        self._busy = self.busy_after_completion

    async def write_gatt_char(self, uuid, data, response=False):
        assert self.callback is not None, "Notifications must be enabled before writing"
        if uuid == DATA_CHAR_UUID:
            assert len(data) <= 20
            self.raster.extend(data)
            self.chunks.append(bytes(data))
            if self.complete_before_flush and len(self.raster) == self.expected_bytes:
                self.complete()
            return
        command = data[2]
        payload = data[6:-2]
        self.events.append(command)
        if command == Command.GET_STATUS:
            self.status_requests += 1
            state = 1 if self._busy else 0
            status = bytes([state, 0, 0, 100, 25, 0, 0, 0, 0, 7 if self.paper_missing else 0])
            self._busy = False
            self.notify(command, status)
        elif command == Command.SET_INTENSITY:
            self.densities.append(payload[0])
        elif command == Command.PRINT_REQUEST:
            self.requests += 1
            self.raster.clear()
            self.expected_bytes = int.from_bytes(payload[:2], "little") * 48
            self.notify(command, bytes([self.accept]))
        elif command == Command.FLUSH and not self.complete_before_flush:
            self.complete()


@pytest.fixture
def transport(monkeypatch):
    devices = []
    sleeps = []
    find = AsyncMock(return_value=SimpleNamespace(name="MXW01", address="test-printer"))
    monkeypatch.setattr(client.BleakScanner, "find_device_by_address", find)

    def create(*args, **kwargs):
        ble = EmulatedBLE(*args, **kwargs)
        devices.append(ble)
        return ble

    original_sleep = asyncio.sleep

    async def fast_sleep(delay):
        sleeps.append(delay)
        await original_sleep(0)

    monkeypatch.setattr(client, "BleakClient", create)
    monkeypatch.setattr(client.asyncio, "sleep", fast_sleep)
    return devices, sleeps, find


def test_three_jobs_wait_for_acceptance_completion_and_idle(transport):
    devices, sleeps, find = transport

    async def run():
        async with AsyncFunPrinter(address="test-printer") as printer:
            devices[0].busy_after_completion = True
            for _ in range(3):
                await printer.print_image(Image.new("L", (384, 2), 0), feed=0, density=150)
                assert devices[0].completions == devices[0].requests

    asyncio.run(run())
    ble = devices[0]
    assert ble.requests == ble.completions == 3
    assert ble.densities == [150, 150, 150]
    assert ble.status_requests == 9  # Before each job, then busy and idle after completion.
    assert ble.events[0] == "subscribed"
    assert not ble.is_connected
    assert all(delay <= 0.25 for delay in sleeps)  # No image-sized blind sleep.
    find.assert_awaited_once_with("test-printer", timeout=3.0)


@pytest.mark.parametrize("failure, message, expected_requests", [
    ("paper_missing", "no paper", 0),
    ("reject", "rejected", 1),
    ("bad_checksum", "checksum", 1),
])
def test_transport_rejections_are_not_reported_as_success(transport, failure, message, expected_requests):
    devices, _, _ = transport

    async def run():
        async with AsyncFunPrinter(address="test-printer") as printer:
            if failure == "reject":
                devices[0].accept = 1
            else:
                setattr(devices[0], failure, True)
            await printer.print_image(Image.new("L", (384, 1), 0), feed=0)

    with pytest.raises(FunPrintJobError, match=message):
        asyncio.run(run())
    assert devices[0].requests == expected_requests
    assert not devices[0].is_connected


def test_missing_third_completion_fails_instead_of_claiming_three_prints(transport, monkeypatch):
    devices, _, _ = transport
    wait_response = AsyncFunPrinter._wait_response

    async def short_wait(self, command, future, timeout):
        return await wait_response(self, command, future, 0.005)

    monkeypatch.setattr(AsyncFunPrinter, "_wait_response", short_wait)
    confirmed = []

    async def run():
        async with AsyncFunPrinter(address="test-printer") as printer:
            devices[0].skip_completion = 3
            for index in range(3):
                await printer.print_image(Image.new("L", (384, 1), 0), feed=0)
                confirmed.append(index)

    with pytest.raises(FunPrintJobError, match="0xAA"):
        asyncio.run(run())
    assert confirmed == [0, 1]
    assert not devices[0].is_connected


def test_completion_arriving_before_flush_is_retained(transport):
    devices, _, _ = transport

    async def run():
        async with AsyncFunPrinter(address="test-printer") as printer:
            devices[0].complete_before_flush = True
            await printer.print_image(Image.new("L", (384, 1), 0), feed=0)

    asyncio.run(run())
    assert devices[0].completions == 1


def test_disconnect_fails_pending_confirmation_immediately():
    async def run():
        printer = AsyncFunPrinter()
        future = printer._arm_response(Command.PRINT_COMPLETE)
        printer._on_disconnect(None)
        with pytest.raises(FunPrintJobError, match="disconnected"):
            await printer._wait_response(Command.PRINT_COMPLETE, future, 10)

    asyncio.run(run())


def test_notification_parser_handles_both_trailers_and_combined_frames():
    parser = NotificationParser()
    old_frame = make_command(Command.PRINT_REQUEST, b"\x00")
    new_frame = response(Command.PRINT_COMPLETE, b"\x00\x03\x03")
    assert parser.feed(b"noise" + old_frame + new_frame) == [
        (Command.PRINT_REQUEST, b"\x00"), (Command.PRINT_COMPLETE, b"\x00\x03\x03"),
    ]


def test_bluetooth_errors_are_connection_errors(monkeypatch):
    monkeypatch.setattr(client.BleakScanner, "find_device_by_address", AsyncMock(side_effect=BleakError("Bluetooth off")))
    with pytest.raises(FunPrintConnectionError, match="Bluetooth off"):
        asyncio.run(AsyncFunPrinter(address="test-printer").connect())


def test_sync_image_calls_close_connections_between_event_loops(transport):
    devices, _, _ = transport
    printer = client.FunPrinter(address="test-printer")
    for _ in range(2):
        printer.print_image(Image.new("L", (384, 1), 0), feed=0, density=150)
    assert len(devices) == 2
    assert all(not device.is_connected and device.densities == [150] for device in devices)


def test_cli_reports_only_two_confirmed_when_third_completion_is_missing(transport, tmp_path, monkeypatch, capsys):
    ble_factory = client.BleakClient

    def skip_third(*args, **kwargs):
        ble = ble_factory(*args, **kwargs)
        ble.skip_completion = 3
        return ble

    wait_response = AsyncFunPrinter._wait_response

    async def short_wait(self, command, future, timeout):
        return await wait_response(self, command, future, 0.005)

    monkeypatch.setattr(client, "BleakClient", skip_third)
    monkeypatch.setattr(AsyncFunPrinter, "_wait_response", short_wait)
    for index in range(3):
        Image.new("L", (384, 1), 0).save(tmp_path / f"photo{index}.png")
    monkeypatch.setattr("sys.argv", ["funprint", "--mac", "test-printer", "folder", str(tmp_path), "--feed", "0"])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert "Confirmed 2/3." in output.out
    assert "Confirmed 3/3." not in output.out
    assert "Done!" not in output.out
    assert "Image 3/3 was not confirmed; 2 previous image(s) confirmed" in output.err
