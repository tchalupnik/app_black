"""Bonecli script."""

from __future__ import annotations

import logging
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated

import anyio
import typer
from yaml import MarkedYAMLError

from boneio.config import ModbusModels
from boneio.logger import configure_logger, setup_logging
from boneio.modbus.models import RegisterType, ValueType
from boneio.version import __version__

os.environ["W1THERMSENSOR_NO_KERNEL_MODULE"] = "1"

_LOGGER = logging.getLogger(__name__)


class UartChoice(str, Enum):
    uart1 = "uart1"
    uart4 = "uart4"


class ParityChoice(str, Enum):
    P = "P"
    E = "E"
    N = "N"


class DeviceChoice(str, Enum):
    # TODO: MISSING CHOICES?
    cwt = "cwt"
    r4dcb08 = "r4dcb08"
    liquid_sensor = "liquid-sensor"
    sht20 = "sht20"
    sht30 = "sht30"
    custom = "custom"


app = typer.Typer(help="boneIO app for BeagleBone Black.")

modbus_app = typer.Typer(help="Modbus commands")
app.add_typer(modbus_app, name="modbus")


@app.command()
def run(
    config: Annotated[
        str,
        typer.Option(
            "-c",
            "--config",
            metavar="path_to_config_dir",
            help="File which contains boneIO configuration",
        ),
    ] = "./config.yaml",
    debug: Annotated[
        int,
        typer.Option("-d", "--debug", count=True, help="Start boneIO in debug mode"),
    ] = 0,
    mqttusername: Annotated[
        str | None,
        typer.Option(help="Mqtt username to use if you don't want provide in file."),
    ] = None,
    mqttpassword: Annotated[
        str | None,
        typer.Option(help="Mqtt password to use if you don't want provide in file."),
    ] = None,
    dry: Annotated[
        bool,
        typer.Option(
            help="Run in dry mode, no changes will be made. Useful for testing configuration."
        ),
    ] = False,
) -> None:
    """Run BoneIO."""
    from boneio.asyncio_ import asyncio_run
    from boneio.runner import start
    from boneio.yaml import ConfigurationError, load_config

    config_file_path = Path(config).resolve()

    setup_logging(debug_level=debug)
    _LOGGER.info("BoneIO %s starting.", __version__)
    try:
        config_parsed = load_config(config_file_path=config_file_path)
        backend_options = {}
        if debug >= 2:
            backend_options["debug"] = True
        asyncio_run(
            start,
            config=config_parsed,
            config_file_path=config_file_path,
            mqttusername=mqttusername,
            mqttpassword=mqttpassword,
            debug=debug,
            dry=dry,
            backend_options=backend_options,
        )
        _LOGGER.info("BoneIO %s exiting.", __version__)
    except (ConfigurationError, MarkedYAMLError) as err:
        _LOGGER.error("Failed to load config. %s Exiting.", err)
        raise typer.Exit(1)


@modbus_app.command("set")
def modbus_set(
    uart: Annotated[UartChoice, typer.Option(help="Choose UART")],
    baudrate: Annotated[int, typer.Option(help="Current baudrate")],
    device: Annotated[
        ModbusModels,
        typer.Option(
            help="Choose device to set modbus address/baudrate. For custom you must provide --custom-value and --custom-register-address"
        ),
    ],
    address: Annotated[
        int, typer.Option(help="Current device address (hex or integer)")
    ] = 1,
    bytesize: Annotated[int, typer.Option(help="Bytesize")] = 8,
    stopbits: Annotated[int, typer.Option(help="stopbits")] = 1,
    parity: Annotated[ParityChoice, typer.Option(help="Parity")] = ParityChoice.N,
    debug: Annotated[
        int,
        typer.Option("-d", "--debug", count=True, help="Start boneIO in debug mode"),
    ] = 0,
    new_address: Annotated[
        int | None, typer.Option(help="Set new address (hex or integer / 1 - 253/)")
    ] = None,
    new_baudrate: Annotated[
        int | None,
        typer.Option(help="Choose new baudrate to set. CWT doesn't work on 1200."),
    ] = None,
    custom_value: Annotated[int | None, typer.Option(help="Set Custom value")] = None,
    custom_register_address: Annotated[
        int | None, typer.Option(help="Register address for custom value")
    ] = None,
) -> None:
    """Set modbus device parameters."""

    from boneio.modbus.modbuscli import async_run_modbus_set
    from boneio.yaml import ConfigurationError

    if new_address is not None and new_baudrate is not None:
        typer.echo(
            "Error: Cannot set both new address and new baudrate at the same time",
            err=True,
        )
        raise typer.Exit(1)

    setup_logging(debug_level=debug)
    _LOGGER.info("BoneIO %s starting.", __version__)
    try:
        configure_logger(debug=debug)
        ret = anyio.run(
            lambda: async_run_modbus_set(
                device=device,
                uart=uart.value,
                address=address,
                baudrate=baudrate,
                parity=parity.value,
                bytesize=bytesize,
                stopbits=stopbits,
                new_baudrate=new_baudrate,
                new_address=new_address,
                custom_address=custom_register_address,
                custom_value=custom_value,
            )
        )
        if ret != 0:
            raise typer.Exit(ret)
    except (ConfigurationError, MarkedYAMLError) as err:
        _LOGGER.error("Failed to load config. %s Exiting.", err)
        raise typer.Exit(1)


@modbus_app.command("get")
def modbus_get(
    uart: Annotated[UartChoice, typer.Option(help="Choose UART")],
    baudrate: Annotated[int, typer.Option(help="Current baudrate")],
    register_type: Annotated[RegisterType, typer.Option(help="Register type")],
    value_type: Annotated[ValueType, typer.Option(help="Value types")],
    address: Annotated[
        int, typer.Option(help="Current device address (hex or integer)")
    ] = 1,
    bytesize: Annotated[int, typer.Option(help="Bytesize")] = 8,
    stopbits: Annotated[int, typer.Option(help="stopbits")] = 1,
    parity: Annotated[ParityChoice, typer.Option(help="Parity")] = ParityChoice.N,
    debug: Annotated[
        int,
        typer.Option("-d", "--debug", count=True, help="Start boneIO in debug mode"),
    ] = 0,
    register_address: Annotated[
        int | None, typer.Option(help="Single register address to read")
    ] = None,
    register_range: Annotated[
        str | None,
        typer.Option(
            help="Register address range in format 'start-stop' (e.g., '1-230')"
        ),
    ] = None,
) -> None:
    """Get modbus register values."""

    from boneio.modbus.modbuscli import async_run_modbus_get
    from boneio.yaml import ConfigurationError

    if register_address is None and register_range is None:
        typer.echo(
            "Error: Either --register-address or --register-range is required", err=True
        )
        raise typer.Exit(1)
    if register_address is not None and register_range is not None:
        typer.echo(
            "Error: Cannot specify both --register-address and --register-range",
            err=True,
        )
        raise typer.Exit(1)

    if register_range is None:
        register_range = f"{register_address}-{register_address}"

    setup_logging(debug_level=debug)
    _LOGGER.info("BoneIO %s starting.", __version__)
    try:
        configure_logger(debug=debug)
        ret = anyio.run(
            lambda: async_run_modbus_get(
                uart=uart.value,
                device_address=address,
                baudrate=baudrate,
                register_type=register_type,
                parity=parity.value,
                bytesize=bytesize,
                stopbits=stopbits,
                value_type=value_type,
                register_range=register_range,
            )
        )
        if ret != 0:
            raise typer.Exit(ret)
    except (ConfigurationError, MarkedYAMLError) as err:
        _LOGGER.error("Failed to load config. %s Exiting.", err)
        raise typer.Exit(1)


@modbus_app.command("search")
def modbus_search(
    uart: Annotated[UartChoice, typer.Option(help="Choose UART")],
    baudrate: Annotated[int, typer.Option(help="Current baudrate")],
    register_address: Annotated[int, typer.Option(help="Register address")],
    register_type: Annotated[RegisterType, typer.Option(help="Register type")],
    bytesize: Annotated[int, typer.Option(help="Bytesize")] = 8,
    stopbits: Annotated[int, typer.Option(help="stopbits")] = 1,
    parity: Annotated[ParityChoice, typer.Option(help="Parity")] = ParityChoice.N,
    debug: Annotated[
        int,
        typer.Option("-d", "--debug", count=True, help="Start boneIO in debug mode"),
    ] = 0,
) -> None:
    """Search for device. Iterate over every address 1-253 with provided register address."""
    from boneio.modbus.modbuscli import async_run_modbus_search
    from boneio.yaml import ConfigurationError

    setup_logging(debug_level=debug)
    _LOGGER.info("BoneIO %s starting.", __version__)
    try:
        configure_logger(debug=debug)
        ret = anyio.run(
            lambda: async_run_modbus_search(
                uart=uart.value,
                baudrate=baudrate,
                register_address=register_address,
                register_type=register_type,
                stopbits=stopbits,
                bytesize=bytesize,
                parity=parity.value,
            )
        )
        if ret != 0:
            raise typer.Exit(ret)
    except (ConfigurationError, MarkedYAMLError) as err:
        _LOGGER.error("Failed to load config. %s Exiting.", err)
        raise typer.Exit(1)


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=version_callback,
            is_eager=True,
            help="Show version and exit",
        ),
    ] = None,
) -> None:
    """boneIO app for BeagleBone Black."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(0)


def main() -> int:
    """Start boneIO with typer."""
    try:
        app()
        return 0
    except typer.Exit as e:
        return e.exit_code if e.exit_code is not None else 0


if __name__ == "__main__":
    sys.exit(main())
