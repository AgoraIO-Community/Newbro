from __future__ import annotations

from dataclasses import dataclass, field

from newbro.protocol import Task, TaskStatus, TaskSummary


@dataclass(slots=True)
class CommunicationEvalScenario:
    name: str
    user_text: str
    initial_tasks: list[Task] = field(default_factory=list)
    initial_summaries: list[TaskSummary] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    forbidden_tools: list[str] = field(default_factory=list)
    expected_tools_when_real_executor: list[str] = field(default_factory=list)
    forbidden_tools_when_mock_only: list[str] = field(default_factory=list)
    forbidden_reply_markers_when_mock_only: list[str] = field(default_factory=list)
    expected_language: str = "same_as_user"


COMMUNICATION_EVAL_SCENARIOS = [
    CommunicationEvalScenario(
        name="create_task_cn",
        user_text="帮我查一下明天上海到北京的航班",
        expected_tools_when_real_executor=["create_task"],
        forbidden_tools_when_mock_only=["create_task"],
        forbidden_tools=["query_task_summary", "control_task"],
    ),
    CommunicationEvalScenario(
        name="create_drawing_task_cn",
        user_text="帮我画一只戴着萝卜帽子的小猫",
        expected_tools_when_real_executor=["create_task"],
        forbidden_tools_when_mock_only=["create_task"],
        forbidden_tools=["query_task_summary", "control_task"],
    ),
    CommunicationEvalScenario(
        name="add_note_cn",
        user_text="给那个邮件任务补一句，语气再简短一点",
        initial_tasks=[
            Task(
                task_id="task-email",
                root_task_id="task-email",
                title="Draft email",
                goal="Draft a customer email reply",
                status=TaskStatus.CREATED,
            )
        ],
        expected_tools=["add_task_note"],
        forbidden_tools=["create_task", "control_task"],
    ),
    CommunicationEvalScenario(
        name="add_constraint_cn",
        user_text="那个邮件任务先别发出去",
        initial_tasks=[
            Task(
                task_id="task-email",
                root_task_id="task-email",
                title="Draft email",
                goal="Draft a customer email reply",
                status=TaskStatus.RUNNING,
            )
        ],
        expected_tools=["add_constraint"],
        forbidden_tools=["create_task"],
    ),
    CommunicationEvalScenario(
        name="query_progress_cn",
        user_text="那个任务现在到哪了",
        initial_tasks=[
            Task(
                task_id="task-report",
                root_task_id="task-report",
                title="Prepare report",
                goal="Prepare the weekly report",
                status=TaskStatus.RUNNING,
            )
        ],
        initial_summaries=[
            TaskSummary(
                task_id="task-report",
                operational_summary="Still gathering numbers.",
                conversational_summary="还在整理数据，已经有初步结果了。",
                latest_user_visible_status="running",
                needs_user_input=False,
            )
        ],
        expected_tools=["query_task_summary"],
        forbidden_tools=["create_task", "control_task"],
    ),
    CommunicationEvalScenario(
        name="pure_chat_cn",
        user_text="你觉得我今天状态怎么样",
        forbidden_tools=[
            "create_task",
            "update_task",
            "add_task_note",
            "add_constraint",
            "control_task",
            "query_task_summary",
            "query_task_detail",
        ],
    ),
    CommunicationEvalScenario(
        name="capability_gated_cpu_usage_en",
        user_text="check my pc cpu usage",
        expected_tools_when_real_executor=["create_task"],
        forbidden_tools_when_mock_only=["create_task"],
        forbidden_reply_markers_when_mock_only=["task manager", "activity monitor"],
    ),
]
