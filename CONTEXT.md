# Newbro Context

## Domain Terms

- **Direct Executor Interaction**: The current core product path where Bro Detail sends text or audio push-to-talk input directly to an executor, Codex first. Idle executor threads create `OutboundTurnRequest` records and start executor-native turns; active executor runs receive direct follow-up instructions. This path bypasses ordinary chat history and suppresses normal Communication notification candidates.
