import pytest

from newbro.blackboard import InMemoryBlackboard
from newbro.execution import SessionManager
from newbro.executors.adapters.mock import MockExecutor
from newbro.protocol import SessionBinding, Task


@pytest.mark.anyio
async def test_session_manager_creates_and_reuses_session():
    store = InMemoryBlackboard()
    manager = SessionManager()
    executor = MockExecutor()
    task = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="Reuse session",
        goal="Reuse session",
    )
    binding = SessionBinding(task_id="task_1", claimed_by="worker-1")

    session_one, binding_one, executor_session_one = await manager.ensure_session(
        store, executor, task, binding
    )
    session_two, binding_two, executor_session_two = await manager.ensure_session(
        store, executor, task, binding_one
    )

    assert session_one.execution_session_id == session_two.execution_session_id
    assert binding_two.session_id == binding_one.session_id
    assert executor_session_one.session_id == executor_session_two.session_id


@pytest.mark.anyio
async def test_session_manager_reuses_session_for_same_continuity_key_across_tasks():
    store = InMemoryBlackboard()
    manager = SessionManager()
    executor = MockExecutor()
    task_one = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="First task",
        goal="First task",
        session_affinity="ws-bro-detail-1",
        metadata={"bro_detail_session_id": "bro-detail-1", "executor_node_id": "node-1"},
    )
    task_two = Task(
        task_id="task_2",
        root_task_id="task_2",
        title="Second task",
        goal="Second task",
        session_affinity="ws-bro-detail-1",
        metadata={"bro_detail_session_id": "bro-detail-1", "executor_node_id": "node-1"},
    )

    session_one, binding_one, executor_session_one = await manager.ensure_session(
        store,
        executor,
        task_one,
        SessionBinding(task_id="task_1", claimed_by="worker-1"),
    )
    session_two, binding_two, executor_session_two = await manager.ensure_session(
        store,
        executor,
        task_two,
        SessionBinding(task_id="task_2", claimed_by="worker-1"),
    )

    assert session_one.execution_session_id == session_two.execution_session_id
    assert session_one.continuity_key == "bro-detail-1"
    assert binding_two.execution_session_id == session_one.execution_session_id
    assert executor_session_one.session_id == executor_session_two.session_id
    assert binding_one.task_id == "task_1"
    assert binding_two.task_id == "task_2"


@pytest.mark.anyio
async def test_session_manager_prefers_explicit_bro_thread_continuity():
    store = InMemoryBlackboard()
    manager = SessionManager()
    executor = MockExecutor()
    task_one = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="First task",
        goal="First task",
        metadata={
            "bro_detail_session_id": "bro-detail-1",
            "bro_thread_id": "bro-thread-selected",
        },
    )
    task_two = Task(
        task_id="task_2",
        root_task_id="task_2",
        title="Second task",
        goal="Second task",
        metadata={
            "bro_detail_session_id": "bro-detail-1",
            "bro_thread_id": "bro-thread-selected",
        },
    )

    session_one, _, _ = await manager.ensure_session(
        store,
        executor,
        task_one,
        SessionBinding(task_id="task_1", claimed_by="worker-1"),
    )
    session_two, _, _ = await manager.ensure_session(
        store,
        executor,
        task_two,
        SessionBinding(task_id="task_2", claimed_by="worker-1"),
    )

    assert session_one.execution_session_id == session_two.execution_session_id
    assert session_one.continuity_key == "bro-thread-selected"


@pytest.mark.anyio
async def test_session_manager_hydrates_imported_codex_thread_resume_handle():
    store = InMemoryBlackboard()
    manager = SessionManager()
    executor = MockExecutor()
    task = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="Imported Codex thread",
        goal="Resume imported Codex thread",
        metadata={
            "bro_thread_id": "codex-import-selected",
            "codex_thread_mode": "resume",
            "codex_import_thread_id": "codex-native-thread-1",
            "codex_import_cwd": "/tmp/imported-cwd",
        },
    )

    session, _, executor_session = await manager.ensure_session(
        store,
        executor,
        task,
        SessionBinding(task_id="task_1", claimed_by="worker-1"),
    )

    assert session.continuity_key == "codex-import-selected"
    assert session.latest_resume_handle is not None
    assert session.latest_resume_handle.executor_id == "codex"
    assert session.latest_resume_handle.session_handle == "codex-native-thread-1"
    assert session.latest_resume_handle.opaque["cwd"] == "/tmp/imported-cwd"
    assert executor_session.metadata["latest_resume_handle"]["session_handle"] == "codex-native-thread-1"
    assert executor_session.metadata["latest_resume_handle"]["opaque"]["cwd"] == "/tmp/imported-cwd"


@pytest.mark.anyio
async def test_session_manager_does_not_reuse_after_continuity_key_or_node_changes():
    store = InMemoryBlackboard()
    manager = SessionManager()
    executor = MockExecutor()
    task_one = Task(
        task_id="task_1",
        root_task_id="task_1",
        title="First task",
        goal="First task",
        session_affinity="ws-bro-detail-1",
        metadata={"bro_detail_session_id": "bro-detail-1", "executor_node_id": "node-1"},
    )
    task_new_generation = Task(
        task_id="task_2",
        root_task_id="task_2",
        title="Second task",
        goal="Second task",
        session_affinity="ws-bro-detail-2",
        metadata={"bro_detail_session_id": "bro-detail-2", "executor_node_id": "node-1"},
    )
    task_new_node = Task(
        task_id="task_3",
        root_task_id="task_3",
        title="Third task",
        goal="Third task",
        session_affinity="ws-bro-detail-1",
        metadata={"bro_detail_session_id": "bro-detail-1", "executor_node_id": "node-2"},
    )

    session_one, _, _ = await manager.ensure_session(
        store,
        executor,
        task_one,
        SessionBinding(task_id="task_1", claimed_by="worker-1"),
    )
    session_new_generation, _, _ = await manager.ensure_session(
        store,
        executor,
        task_new_generation,
        SessionBinding(task_id="task_2", claimed_by="worker-1"),
    )
    session_new_node, _, _ = await manager.ensure_session(
        store,
        executor,
        task_new_node,
        SessionBinding(task_id="task_3", claimed_by="worker-1"),
    )

    assert session_new_generation.execution_session_id != session_one.execution_session_id
    assert session_new_node.execution_session_id != session_one.execution_session_id
