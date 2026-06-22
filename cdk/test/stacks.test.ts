import * as cdk from 'aws-cdk-lib';
import { Template } from 'aws-cdk-lib/assertions';
import { DataStack } from '../lib/data-stack';

describe('DataStack', () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App();
    const stack = new DataStack(app, 'TestDataStack');
    template = Template.fromStack(stack);
  });

  test('creates nine DynamoDB tables', () => {
    template.resourceCountIs('AWS::DynamoDB::Table', 9);
  });

  test('CatProfiles table has correct partition key', () => {
    template.hasResource('AWS::DynamoDB::Table', {
      Properties: {
        KeySchema: [
          { AttributeName: 'cat_id', KeyType: 'HASH' },
        ],
      },
    });
  });
});
