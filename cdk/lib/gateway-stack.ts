import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as iam from 'aws-cdk-lib/aws-iam';

export interface GatewayStackProps extends cdk.StackProps {
  lambdaArns: {
    catProfile: string;
    device: string;
    feeding: string;
    health: string;
    vet: string;
  };
}

/**
 * AgentCore Gateway — exposes MCP protocol to agent runtimes and
 * translates tool calls into direct Lambda invocations.
 */
export class GatewayStack extends cdk.Stack {
  readonly gatewayUrl: cdk.CfnOutput;
  readonly gatewayUrlValue: string;

  constructor(scope: Construct, id: string, props: GatewayStackProps) {
    super(scope, id, props);

    // IAM role for the Gateway to invoke Lambdas
    const gatewayRole = new iam.Role(this, 'GatewayRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      description: 'Allows AgentCore Gateway to invoke cat-demo Lambda functions',
    });
    gatewayRole.addToPolicy(new iam.PolicyStatement({
      actions: ['lambda:InvokeFunction'],
      resources: [
        props.lambdaArns.catProfile,
        props.lambdaArns.device,
        props.lambdaArns.feeding,
        props.lambdaArns.health,
        props.lambdaArns.vet,
      ],
    }));

    // Gateway resource
    const gateway = new cdk.CfnResource(this, 'Gateway', {
      type: 'AWS::BedrockAgentCore::Gateway',
      properties: {
        Name: 'cat-care-gateway',
        ProtocolType: 'MCP',
        AuthorizerType: 'NONE',
        RoleArn: gatewayRole.roleArn,
      },
    });

    // --- GatewayTargets ---

    // cat-profile target (3 tools)
    const catProfileTarget = new cdk.CfnResource(this, 'CatProfileTarget', {
      type: 'AWS::BedrockAgentCore::GatewayTarget',
      properties: {
        GatewayIdentifier: gateway.getAtt('GatewayIdentifier'),
        Name: 'cat-profile',
        CredentialProviderConfigurations: [{
          CredentialProviderType: 'GATEWAY_IAM_ROLE',
        }],

        TargetConfiguration: {
          Mcp: {
            Lambda: {
              LambdaArn: props.lambdaArns.catProfile,
              ToolSchema: {
                InlinePayload: [
                  {
                    Name: 'get_cat_profile',
                    Description: 'Look up a cat\'s profile by ID',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        cat_id: { Type: 'string', Description: 'The ID of the cat to look up' },
                      },
                      Required: ['cat_id'],
                    },
                  },
                  {
                    Name: 'list_cats',
                    Description: 'List all registered cats',
                    InputSchema: {
                      Type: 'object',
                      Properties: {},
                      Required: [],
                    },
                  },
                  {
                    Name: 'lookup_cat_by_name',
                    Description: 'Look up a cat by name or nickname',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        name: { Type: 'string', Description: 'Cat name or nickname to search for' },
                      },
                      Required: ['name'],
                    },
                  },
                ],
              },
            },
          },
        },
      },
    });
    catProfileTarget.addDependency(gateway);

    // feeding target (2 tools)
    const feedingTarget = new cdk.CfnResource(this, 'FeedingTarget', {
      type: 'AWS::BedrockAgentCore::GatewayTarget',
      properties: {
        GatewayIdentifier: gateway.getAtt('GatewayIdentifier'),
        Name: 'feeding',
        CredentialProviderConfigurations: [{
          CredentialProviderType: 'GATEWAY_IAM_ROLE',
        }],

        TargetConfiguration: {
          Mcp: {
            Lambda: {
              LambdaArn: props.lambdaArns.feeding,
              ToolSchema: {
                InlinePayload: [
                  {
                    Name: 'get_feedings',
                    Description: 'Get recent feeding history for a cat',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        cat_id: { Type: 'string', Description: 'The ID of the cat' },
                      },
                      Required: ['cat_id'],
                    },
                  },
                  {
                    Name: 'record_feeding',
                    Description: 'Record a new feeding event',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        cat_id: { Type: 'string', Description: 'The ID of the cat' },
                        amount_grams: { Type: 'integer', Description: 'Amount of food in grams' },
                        food_type: { Type: 'string', Description: 'Type of food' },
                      },
                      Required: ['cat_id', 'amount_grams', 'food_type'],
                    },
                  },
                ],
              },
            },
          },
        },
      },
    });
    feedingTarget.addDependency(gateway);

    // health target (2 tools)
    const healthTarget = new cdk.CfnResource(this, 'HealthTarget', {
      type: 'AWS::BedrockAgentCore::GatewayTarget',
      properties: {
        GatewayIdentifier: gateway.getAtt('GatewayIdentifier'),
        Name: 'health',
        CredentialProviderConfigurations: [{
          CredentialProviderType: 'GATEWAY_IAM_ROLE',
        }],

        TargetConfiguration: {
          Mcp: {
            Lambda: {
              LambdaArn: props.lambdaArns.health,
              ToolSchema: {
                InlinePayload: [
                  {
                    Name: 'get_health_metrics',
                    Description: 'Get recent health metrics for a cat',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        cat_id: { Type: 'string', Description: 'The ID of the cat' },
                      },
                      Required: ['cat_id'],
                    },
                  },
                  {
                    Name: 'get_health_alerts',
                    Description: 'Get active health alerts for a cat',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        cat_id: { Type: 'string', Description: 'The ID of the cat' },
                      },
                      Required: ['cat_id'],
                    },
                  },
                  {
                    Name: 'get_daily_rollup',
                    Description: 'Get daily nutrition rollup (total grams, wet/dry breakdown, feeding count) for a cat. Returns last 7 days if no date specified.',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        cat_id: { Type: 'string', Description: 'The ID of the cat' },
                        date: { Type: 'string', Description: 'Optional YYYY-MM-DD date to get a specific day' },
                      },
                      Required: ['cat_id'],
                    },
                  },
                  {
                    Name: 'get_health_summary',
                    Description: 'Get daily health summary (avg weight, activity stats) for a cat. Returns last 7 days if no date specified.',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        cat_id: { Type: 'string', Description: 'The ID of the cat' },
                        date: { Type: 'string', Description: 'Optional YYYY-MM-DD date to get a specific day' },
                      },
                      Required: ['cat_id'],
                    },
                  },
                ],
              },
            },
          },
        },
      },
    });
    healthTarget.addDependency(gateway);

    // device target (3 tools)
    const deviceTarget = new cdk.CfnResource(this, 'DeviceTarget', {
      type: 'AWS::BedrockAgentCore::GatewayTarget',
      properties: {
        GatewayIdentifier: gateway.getAtt('GatewayIdentifier'),
        Name: 'device',
        CredentialProviderConfigurations: [{
          CredentialProviderType: 'GATEWAY_IAM_ROLE',
        }],

        TargetConfiguration: {
          Mcp: {
            Lambda: {
              LambdaArn: props.lambdaArns.device,
              ToolSchema: {
                InlinePayload: [
                  {
                    Name: 'list_devices',
                    Description: 'List all registered IoT devices',
                    InputSchema: {
                      Type: 'object',
                      Properties: {},
                      Required: [],
                    },
                  },
                  {
                    Name: 'get_device',
                    Description: 'Get details for a specific device',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        device_id: { Type: 'string', Description: 'The ID of the device' },
                      },
                      Required: ['device_id'],
                    },
                  },
                  {
                    Name: 'send_device_command',
                    Description: 'Send a command to an IoT device',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        device_id: { Type: 'string', Description: 'The ID of the device' },
                        command: { Type: 'string', Description: 'The command to send' },
                      },
                      Required: ['device_id', 'command'],
                    },
                  },
                ],
              },
            },
          },
        },
      },
    });
    deviceTarget.addDependency(gateway);

    // vet target (3 tools: get_vet_records, create_vet_record, recommend_feeding)
    const vetTarget = new cdk.CfnResource(this, 'VetTarget', {
      type: 'AWS::BedrockAgentCore::GatewayTarget',
      properties: {
        GatewayIdentifier: gateway.getAtt('GatewayIdentifier'),
        Name: 'vet',
        CredentialProviderConfigurations: [{
          CredentialProviderType: 'GATEWAY_IAM_ROLE',
        }],
        TargetConfiguration: {
          Mcp: {
            Lambda: {
              LambdaArn: props.lambdaArns.vet,
              ToolSchema: {
                InlinePayload: [
                  {
                    Name: 'get_vet_records',
                    Description: 'Get vet records (dietary restrictions, post-op holds, allergies, weight targets) for a cat. These override standard feeding rules.',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        cat_id: { Type: 'string', Description: 'The ID of the cat' },
                        active_only: { Type: 'boolean', Description: 'If true (default), only return currently active records' },
                      },
                      Required: ['cat_id'],
                    },
                  },
                  {
                    Name: 'create_vet_record',
                    Description: 'Create a new vet record for a cat',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        cat_id: { Type: 'string', Description: 'The ID of the cat' },
                        record_type: { Type: 'string', Description: 'One of: dietary_restriction, post_op_hold, allergy, weight_target' },
                        effective_from: { Type: 'string', Description: 'ISO timestamp when this record takes effect' },
                        effective_until: { Type: 'string', Description: 'ISO timestamp when this record expires (null for open-ended)' },
                        details: { Type: 'object', Description: 'Type-specific payload (e.g. restriction details, allergen info)' },
                      },
                      Required: ['cat_id', 'record_type'],
                    },
                  },
                  {
                    Name: 'recommend_feeding',
                    Description: 'Get a feeding recommendation for a cat based on their profile, history, vet records, and health status',
                    InputSchema: {
                      Type: 'object',
                      Properties: {
                        cat_id: { Type: 'string', Description: 'The ID of the cat' },
                      },
                      Required: ['cat_id'],
                    },
                  },
                ],
              },
            },
          },
        },
      },
    });
    vetTarget.addDependency(gateway);

    // --- Tracing: deliver gateway spans to X-Ray ---
    //
    // AgentCore Gateway has no `TracingEnabled` property on the CFN
    // resource itself. Tracing is configured via the generic
    // CloudWatch Logs delivery model: a DeliverySource with
    // logType=TRACES paired with a DeliveryDestination of type XRAY.
    //
    // Prerequisite (one-time, per account/region, NOT in CDK):
    //   aws xray update-trace-segment-destination --destination CloudWatchLogs
    // Without Transaction Search enabled the spans are accepted but
    // never indexed for the GenAI Observability dashboard.
    // See observability-stack.ts for the rationale.
    const tracesSource = new cdk.CfnResource(this, 'GatewayTracesSource', {
      type: 'AWS::Logs::DeliverySource',
      properties: {
        Name: 'cat-care-gateway-traces',
        LogType: 'TRACES',
        ResourceArn: gateway.getAtt('GatewayArn'),
      },
    });
    tracesSource.addDependency(gateway);

    const tracesDestination = new cdk.CfnResource(this, 'GatewayTracesDestination', {
      type: 'AWS::Logs::DeliveryDestination',
      properties: {
        Name: 'cat-care-gateway-traces-xray',
        DeliveryDestinationType: 'XRAY',
      },
    });

    const tracesDelivery = new cdk.CfnResource(this, 'GatewayTracesDelivery', {
      type: 'AWS::Logs::Delivery',
      properties: {
        DeliverySourceName: tracesSource.ref,
        DeliveryDestinationArn: tracesDestination.getAtt('Arn'),
      },
    });
    tracesDelivery.addDependency(tracesSource);
    tracesDelivery.addDependency(tracesDestination);

    // Export Gateway URL
    this.gatewayUrlValue = cdk.Token.asString(gateway.getAtt('GatewayUrl'));
    this.gatewayUrl = new cdk.CfnOutput(this, 'GatewayUrl', {
      value: this.gatewayUrlValue,
      description: 'AgentCore Gateway MCP endpoint URL',
    });
  }
}
