# Public Onboarding and Ownership

Newbro's first hosted public path is self-signup gated by a shared access code
and owner-scoped after signup.

The public runtime still keeps Communication Brain, Execution Brain, shared
blackboard, connectors, and detached executor nodes as separate boundaries. The
ownership layer only decides which browser user may access a runtime object.

## Accounts and Sessions

The hosted service configures one fixed signup code with
`NEWBRO_SIGNUP_INVITE_CODE`. A browser user signs up with an email address and
that code. The code is only an access gate; every successful signup creates a
new lightweight user record, even if the email was used before.

Operators may still create legacy invite codes with:

```bash
newbro invite create
newbro invite create friend-code --email user@example.com
```

Signup or legacy invite redemption creates an HttpOnly `newbro_session`
browser cookie. Browser routes for sessions, conversations, drafts, personas,
executor nodes, and voice preparation require that cookie. Logout clears the
cookie, drops the current browser shell session state, and returns the browser
to the signup gate.

The bootstrap route creates or resumes the user's default runtime session,
ensures a default Bro/persona, and lets the frontend open Bro Detail directly.
The frontend does not start voice or expose normal Bro Detail controls until
that Bro is bound to a user-owned executor node.

## Owned Objects

The public auth store owns these bindings:

- browser session token to user
- runtime session id to user
- persona id to user
- executor node id to user

User B must not list, read, mutate, bind, reveal credentials for, or use User
A's owned objects. Cross-user misses return `404` so object existence is not
confirmed.

Detached executor nodes still authenticate to `/api/executors/control` with
their node id and node token. Browser ownership controls who can create, reveal,
rotate, bind, and delete those nodes.

## Voice and Connectors

The hosted service owns OpenAI and Agora credentials. Browser voice starts from
Bro Detail through same-origin connector routes under `/api/connectors/...`.

Bro Detail is node-gated for runtime Bros. If the active Bro has no
`executor_node_id`, the detail route shows an inline setup panel instead of the
voice bar, draft controls, task controls, or normal workspace. The setup panel
creates a private executor node, binds that node to the Bro, and shows a
copyable `newbro executor run ...` command. The normal Bro Detail workspace
unlocks only after the frontend refreshes state and observes the binding.

Agora ConvoAI and STT browser prepare/start paths are owner-scoped to the
current runtime session. Connector-to-runtime callbacks use the internal
connector token instead of browser cookies.

## Waiting for Execution

Draft confirmation may create a task before the user's bound local executor
node is live. In that case the task stays in `waiting_executor`.

For an already-bound Bro, Bro Detail shows a "Connect Codex to run" state and
can reveal a copyable local node command for the bound node.
