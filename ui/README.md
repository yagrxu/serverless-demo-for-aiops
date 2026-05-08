# UIs

Three React/TypeScript frontends served through CloudFront (`UiStack`):

| UI                  | Path on CloudFront     | Purpose                                  |
|---------------------|------------------------|------------------------------------------|
| `chatbot`           | `/`                    | Talk to the AgentCore entrypoint.        |
| `device-simulator`  | `/device-simulator`    | Fake devices that POST telemetry / commands. |
| `admin-console`     | `/admin-console`       | CRUD cats, browse feedings, health, alerts. |

Build each with `npm run build` in its folder. The CDK `UiStack` picks up
`ui/<name>/dist` and uploads it to the CloudFront-fronted S3 bucket.
If the `dist/` folder is missing, the stack falls back to a placeholder page.

No Cognito: the UIs are public but served only through CloudFront + HTTPS,
with the S3 bucket locked down (Origin Access Control, block public access).
