from __future__ import annotations

from typing import Any
import asyncio
import secrets

from newbro.cli import factories as cli_factories
from newbro.cli.commands import doctor as doctor_command
from newbro.cli.commands import executor_settings as executor_settings_command
from newbro.cli.commands import run as run_command
from newbro.cli.commands import service as service_command_impl
from newbro.cli.commands import setup as setup_command
from newbro.cli.commands import status as status_command


def dispatch(args: Any, app: Any) -> int:
    handlers = {
        "setup": cmd_setup,
        "dev": cmd_dev,
        "backend": cmd_backend,
        "frontend": cmd_frontend,
        "doctor": cmd_doctor,
        "status": cmd_status,
        "start": cmd_start,
        "connector": cmd_connector,
        "executor": cmd_executor,
        "service": cmd_service,
        "invite": cmd_invite,
    }
    return handlers[args.command](args, app)


def cmd_setup(args: Any, app: Any) -> int:
    return setup_command.run_setup(args, cli_factories.setup_context(app), cli_factories.setup_callbacks(app))


def cmd_dev(args: Any, app: Any) -> int:
    return run_command.run_dev(args, cli_factories.run_context(app), cli_factories.run_callbacks(args, app))


def cmd_backend(args: Any, app: Any) -> int:
    return run_command.run_backend(args, cli_factories.run_context(app), cli_factories.run_callbacks(args, app))


def cmd_start(args: Any, app: Any) -> int:
    return run_command.run_start(args, cli_factories.run_context(app), cli_factories.run_callbacks(args, app))


def cmd_frontend(args: Any, app: Any) -> int:
    return run_command.run_frontend(args, cli_factories.run_context(app), cli_factories.run_callbacks(args, app))


def cmd_doctor(args: Any, app: Any) -> int:
    return doctor_command.run_doctor(
        cli_factories.doctor_context(args, app),
        cli_factories.doctor_callbacks(args, app),
    )


def cmd_status(args: Any, app: Any) -> int:
    return status_command.run_status(
        cli_factories.status_context(args, app),
        cli_factories.status_callbacks(args, app),
    )


def cmd_connector(args: Any, app: Any) -> int:
    if args.connector_command == "setup":
        return setup_command.run_connector_setup(args, cli_factories.setup_context(app), cli_factories.setup_callbacks(app))
    if args.connector_command == "run":
        return run_command.run_connector(args, cli_factories.run_context(app), cli_factories.run_callbacks(args, app))
    raise app.CliError(f"Unknown connector command: {args.connector_command}")


def cmd_executor(args: Any, app: Any) -> int:
    if args.executor_command == "setup":
        return setup_command.run_executor_setup(args, cli_factories.setup_context(app), cli_factories.setup_callbacks(app))
    if args.executor_command == "probe":
        return executor_settings_command.run_executor_probe(args, app)
    if args.executor_command == "use":
        return executor_settings_command.run_executor_use(args, app)
    if args.executor_command == "run":
        return run_command.run_executor(args, cli_factories.run_context(app), cli_factories.run_callbacks(args, app))
    raise app.CliError(f"Unknown executor command: {args.executor_command}")


def cmd_service(args: Any, app: Any) -> int:
    if args.service_command == "install":
        return service_command_impl.install_service(args, cli_factories.service_context(app), cli_factories.service_callbacks(app))
    if args.service_command in {"start", "stop", "restart"}:
        return service_command_impl.lifecycle_service(
            args.service_command,
            cli_factories.service_context(app),
            cli_factories.service_callbacks(app),
        )
    raise app.CliError(f"Unknown service command: {args.service_command}")


def cmd_invite(args: Any, app: Any) -> int:
    if args.invite_command == "create":
        return cmd_invite_create(args, app)
    raise app.CliError(f"Unknown invite command: {args.invite_command}")


def cmd_invite_create(args: Any, app: Any) -> int:
    from newbro.api.public_auth import PublicAuthStore

    code = args.code.strip() if args.code else secrets.token_urlsafe(12)
    if not code:
        raise app.CliError("Invite code cannot be empty.")
    store = PublicAuthStore()
    asyncio.run(store.create_invite(code, email=args.email))
    print(code)
    return 0
