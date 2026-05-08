export interface AppConfig {
  projectName: string;
  alarmEmail?: string;
  // UI bundles live in ui/<name>/dist and are uploaded to CloudFront-fronted S3.
  uiBundles: { name: string; path: string }[];
  // Toggle deploying the AgentCore runtime (agents/*). Requires Docker locally.
  deployAgents: boolean;
}

export const defaultConfig: AppConfig = {
  projectName: 'aiops-cat-demo',
  uiBundles: [
    { name: 'chatbot', path: '../ui/chatbot/dist' },
    { name: 'device-simulator', path: '../ui/device-simulator/dist' },
    { name: 'admin-console', path: '../ui/admin-console/dist' },
  ],
  deployAgents: true,
};
