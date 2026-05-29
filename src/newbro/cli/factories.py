from __future__ import annotations

from typing import Any

from newbro.cli import command_specs
from newbro.cli import config_files
from newbro.cli import prompts as cli_prompts
from newbro.cli import service_support
from newbro.cli.commands import doctor as doctor_command
from newbro.cli.commands import run as run_command
from newbro.cli.commands import service as service_command_impl
from newbro.cli.commands import setup as setup_command
from newbro.cli.commands import status as status_command
from newbro.cli import setup_resolvers
from newbro.cli import systemd as cli_systemd


def run_context(app: Any) -> run_command.RunContext:
    return run_command.RunContext(root=app.ROOT, frontend=app.FRONTEND)


def run_callbacks(args: Any, app: Any) -> run_command.RunCallbacks:
    return run_command.RunCallbacks(
        require_venv_python=lambda: app.require_venv_python(),
        service_runtime_python_path=app.service_runtime_python_path,
        executor_run_python_path=app.executor_run_python_path,
        executor_run_cwd=app.executor_run_cwd,
        ensure_frontend_build_ready=app.ensure_frontend_build_ready,
        service_command=lambda python, host, port: command_specs.service_command(
            python,
            host,
            port,
            reload=args.command == "dev",
        ),
        backend_command=lambda python, host, port: command_specs.backend_command(
            python,
            host,
            port,
            reload=True,
        ),
        frontend_dev_command=app.frontend_dev_command,
        connector_command=lambda python, host, port, reload: command_specs.connector_command(
            python,
            host,
            port,
            reload=reload,
        ),
        executor_node_command=lambda python: app.executor_node_command(
            python,
            base_url=args.base_url,
            node_id=args.node_id,
            token=args.token,
            enabled_executors=args.enabled_executor or None,
            acpx_agent=args.acpx_agent,
            audio_language=args.audio_language,
            whisper_model=args.whisper_model,
        ),
        load_connector_settings_if_enabled=app.load_connector_settings_if_enabled,
        load_connector_settings=app.load_connector_settings,
        ensure_executor_runtime_configured=lambda: app._ensure_executor_runtime_configured_for_run(
            enabled_executors_override=args.enabled_executor or None,
        ),
        run_checked=lambda command, cwd: app.run_checked(command, cwd=cwd),
        run_managed_processes=app.run_managed_processes,
    )


def service_context(app: Any) -> service_command_impl.ServiceContext:
    return service_command_impl.ServiceContext(root=app.ROOT, systemd_unit_name=app.SYSTEMD_UNIT_NAME)


def service_callbacks(app: Any) -> service_command_impl.ServiceCallbacks:
    return service_command_impl.ServiceCallbacks(
        ensure_install_supported=lambda: service_support.ensure_service_install_supported(
            platform=app.sys.platform,
            cli_name=app.CLI_NAME,
            cli_error=app.CliError,
        ),
        ensure_manager_available=lambda: service_support.ensure_service_manager_available(
            platform=app.sys.platform,
            shutil_module=app.shutil,
            os_module=app.os,
            cli_name=app.CLI_NAME,
            cli_error=app.CliError,
        ),
        current_user=lambda: app.getpass.getuser(),
        user_home=lambda: app.ENV_LOCAL.parent.parent,
        ensure_runtime_ready=lambda: service_support.ensure_service_runtime_ready(
            root=app.ROOT,
            frontend=app.FRONTEND,
            venv_dir=app.VENV_DIR,
            sys_module=app.sys,
            require_venv_python=app.require_venv_python,
            run_checked=lambda command, cwd: app.run_checked(command, cwd=cwd),
            bootstrap_setup_files=app.bootstrap_setup_files,
            openai_api_key_present=app.openai_api_key_present,
            frontend_install_command=lambda: command_specs.frontend_install_command(app.preferred_frontend_tool()),
            frontend_build_command=lambda: command_specs.frontend_build_command(app.preferred_frontend_tool()),
            env_file_label=app.format_user_path(app.ENV_LOCAL),
        ),
        ensure_cli_ready=lambda venv_python: service_support.ensure_service_cli_ready(
            venv_python=venv_python,
            cli_name=app.CLI_NAME,
            root_launcher=app.ROOT_LAUNCHER,
            os_module=app.os,
            cli_error=app.CliError,
        ),
        render_unit=lambda user, home, workdir, cli_bin, host, port: cli_systemd.render_service_unit(
            user=user,
            home=home,
            workdir=workdir,
            cli_bin=cli_bin,
            host=host,
            public_port=port,
        ),
        install_unit=lambda unit_text: cli_systemd.install_service_unit(
            unit_text,
            root=app.ROOT,
            service_unit_path=app.service_unit_path(),
            systemd_unit_name=app.SYSTEMD_UNIT_NAME,
            run_privileged_checked=lambda command, cwd: service_support.run_privileged_checked(
                command,
                cwd=cwd,
                os_module=app.os,
                run_checked=lambda checked_command, workdir: app.run_checked(checked_command, cwd=workdir),
            ),
        ),
        service_unit_path=app.service_unit_path,
        run_privileged_checked=lambda command, cwd: service_support.run_privileged_checked(
            command,
            cwd=cwd,
            os_module=app.os,
            run_checked=lambda checked_command, workdir: app.run_checked(checked_command, cwd=workdir),
        ),
    )


def setup_context(app: Any) -> setup_command.SetupContext:
    return setup_command.SetupContext(
        cli_name=app.CLI_NAME,
        root_launcher=app.ROOT_LAUNCHER,
        env_file=app.ENV_LOCAL,
    )


def setup_callbacks(app: Any) -> setup_command.SetupCallbacks:
    return setup_command.SetupCallbacks(
        setup_can_prompt=app.setup_can_prompt,
        bootstrap_setup_files=app.bootstrap_setup_files,
        load_env_template=lambda: config_files.load_env_template(app.DEFAULT_ENV_TEMPLATE_LINES),
        load_env_assignments=config_files.load_env_assignments,
        connector_config_path=lambda: app.ENV_LOCAL.with_name("config.yaml"),
        load_existing_connector_yaml_for_setup=config_files.load_existing_connector_yaml_for_setup,
        load_existing_connector_yaml=config_files.load_existing_connector_yaml,
        resolve_setup_values=lambda **kwargs: config_files.resolve_setup_values(
            **{key: value for key, value in kwargs.items() if key != "existing_config_yaml"},
            interactive_setup_keys=app.INTERACTIVE_SETUP_KEYS,
            openai_key=app.OPENAI_KEY,
            openai_placeholder="your_openai_api_key_here",
            env_file_label=app.format_user_path(app.ENV_LOCAL),
            prompt_secret_value=lambda name, default_value: cli_prompts.prompt_secret_value(
                name,
                default_value=default_value,
                getpass_module=app.getpass,
            ),
            cli_error=app.CliError,
        ),
        resolve_connector_setup_values=lambda **kwargs: setup_resolvers.resolve_connector_setup_values(
            **kwargs,
            callbacks=setup_resolution_callbacks(app),
        ),
        resolve_executor_setup_values=lambda **kwargs: setup_resolvers.resolve_executor_setup_values(
            **kwargs,
            callbacks=setup_resolution_callbacks(app),
        ),
        render_connector_config=config_files.render_connector_config,
        resolved_runtime_config=lambda raw, values: config_files.resolved_runtime_config(
            raw,
            values,
            removed_keys=app.REMOVED_RUNTIME_KEYS,
        ),
        existing_connector_host_config=config_files.existing_connector_host_config,
        existing_connectors_config=config_files.existing_connectors_config,
        existing_executor_node_config=config_files.existing_executor_node_config,
        existing_executors_config=config_files.existing_executors_config,
        write_env_file=config_files.write_env_file,
        write_connector_config_if_needed=lambda result: config_files.write_connector_config_if_needed(
            result,
            format_user_path=app.format_user_path,
        ),
        connector_setup_result=config_files.ConnectorSetupResult,
        format_user_path=app.format_user_path,
        cli_error=app.CliError,
        environ=app.os.environ,
        legacy_real_executor_env_keys=app.LEGACY_REAL_EXECUTOR_ENV_KEYS,
    )


def setup_resolution_callbacks(app: Any) -> setup_resolvers.SetupResolutionCallbacks:
    return setup_resolvers.SetupResolutionCallbacks(
        connector_config_path=lambda: app.ENV_LOCAL.with_name("config.yaml"),
        coerce_bool_config_value=config_files.coerce_bool_config_value,
        existing_yaml_value=config_files.existing_yaml_value,
        existing_executor_node_config=config_files.existing_executor_node_config,
        existing_executors_config=config_files.existing_executors_config,
        existing_connector_host_config=config_files.existing_connector_host_config,
        existing_connectors_config=config_files.existing_connectors_config,
        existing_runtime_config=lambda raw: config_files.existing_runtime_config(
            raw,
            removed_keys=app.REMOVED_RUNTIME_KEYS,
        ),
        existing_executor_enabled_types=config_files.existing_executor_enabled_types,
        resolved_runtime_config=lambda raw, values: config_files.resolved_runtime_config(
            raw,
            values,
            removed_keys=app.REMOVED_RUNTIME_KEYS,
        ),
        default_connector_host_config=config_files.default_connector_host_config,
        render_connector_config=config_files.render_connector_config,
        pick_env_value=config_files.pick_env_value,
        parse_bool_value=lambda value: config_files.parse_bool_value(
            value,
            truthy_values=app.TRUTHY_VALUES,
            falsy_values=app.FALSY_VALUES,
        ),
        prompt_bool_value=lambda label, default: cli_prompts.prompt_bool_value(
            label,
            default=default,
            parse_bool_value=lambda value: config_files.parse_bool_value(
                value,
                truthy_values=app.TRUTHY_VALUES,
                falsy_values=app.FALSY_VALUES,
            ),
        ),
        prompt_connector_selection=lambda: cli_prompts.prompt_connector_selection(
            list_available_connector_modules=app.list_available_connector_modules,
            cli_error=app.CliError,
        ),
        prompt_text_value=cli_prompts.prompt_text_value,
        prompt_executor_selection=cli_prompts.prompt_executor_selection,
        detected_codex_command=app._detected_codex_command,
        command_available=app._command_available,
        resolve_agora_connector_setup_values=lambda existing_values, environ, existing_connector_yaml: setup_resolvers.resolve_agora_connector_setup_values(
            existing_values,
            environ,
            existing_connector_yaml,
            setup_resolvers.AgoraSetupCallbacks(
                prompt_text_value=cli_prompts.prompt_text_value,
                prompt_secret_value=lambda name, default_value: cli_prompts.prompt_secret_value(
                    name,
                    default_value=default_value,
                    getpass_module=app.getpass,
                ),
                prompt_choice_value=cli_prompts.prompt_choice_value,
                pick_env_value=config_files.pick_env_value,
                normalize_optional_value=config_files.normalize_optional_value,
                existing_connector_block=config_files.existing_connector_block,
                existing_nested_value=config_files.existing_nested_value,
            ),
        ),
    )


def doctor_context(args: Any, app: Any) -> doctor_command.DoctorContext:
    return doctor_command.DoctorContext(
        root_launcher=app.ROOT_LAUNCHER,
        python_executable=app.sys.executable,
        env_file=app.ENV_LOCAL,
        venv_dir=app.VENV_DIR,
        venv_python=app.venv_python_path(),
        backend_port=args.backend_port,
        frontend_port=args.frontend_port,
    )


def doctor_callbacks(args: Any, app: Any) -> doctor_command.DoctorCallbacks:
    return doctor_command.DoctorCallbacks(
        report_path=app.report_path,
        report_command=lambda name: app.report_command(name),
        report_optional_command=lambda name: app.report_command(name, required=False),
        report_port=app.report_port,
        print_check=app._print_check,
        openai_api_key_present=app.openai_api_key_present,
        report_connector_status=lambda: app.report_connector_status(args),
    )


def status_context(args: Any, app: Any) -> status_command.StatusContext:
    config_path = app.connector_config_path()
    return status_command.StatusContext(
        root_launcher=app.ROOT_LAUNCHER,
        python_executable=app.sys.executable,
        env_file=app.ENV_LOCAL,
        config_file=config_path,
        venv_python=app.venv_python_path(),
        frontend_build_index=app.frontend_build_index_path(),
        backend_port=args.backend_port,
        frontend_port=args.frontend_port,
        backend_health_url=f"http://127.0.0.1:{args.backend_port}/api/health",
        frontend_url=f"http://127.0.0.1:{args.frontend_port}/",
        executor_invocation=app.executor_cli_invocation(),
    )


def status_callbacks(args: Any, app: Any) -> status_command.StatusCallbacks:
    return status_command.StatusCallbacks(
        report_path=app.report_path,
        report_command=lambda name: app.report_command(name),
        report_optional_command=lambda name: app.report_command(name, required=False),
        report_port=app.report_port,
        report_reachability=app.report_reachability,
        print_check=app._print_check,
        openai_api_key_present=app.openai_api_key_present,
        config_parse_error=lambda path: config_files.load_existing_connector_yaml_for_setup(path)[1],
        report_connector_status=lambda: app.report_connector_status(args),
        executor_enabled_families=lambda: list(app.load_executor_node_settings().enabled_executors),
    )
