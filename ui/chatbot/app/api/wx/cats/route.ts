import { NextResponse } from 'next/server';
import { verifyWxToken } from '@/lib/wx-auth';
import { DynamoDBClient } from '@aws-sdk/client-dynamodb';
import { DynamoDBDocumentClient, ScanCommand } from '@aws-sdk/lib-dynamodb';

const CAT_PROFILES_TABLE = process.env.CAT_PROFILES_TABLE || 'CatProfiles';

const ddb = DynamoDBDocumentClient.from(
  new DynamoDBClient({
    region: process.env.AWS_REGION || 'us-east-1',
    ...(process.env.LOCAL_MODE === 'true' && {
      endpoint: 'http://localhost:8001',
      credentials: { accessKeyId: 'local', secretAccessKey: 'local' },
    }),
  }),
);

/**
 * GET /api/wx/cats
 * Auth: Bearer <jwt>
 * Returns: { cats: Array<{ cat_id, name, breed, age_years }> }
 */
export async function GET(request: Request) {
  const session = await verifyWxToken(request);
  if (!session) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  const result = await ddb.send(new ScanCommand({
    TableName: CAT_PROFILES_TABLE,
    ProjectionExpression: 'cat_id, #n, breed, age_years',
    ExpressionAttributeNames: { '#n': 'name' },
  }));

  const cats = (result.Items || []).map(item => ({
    cat_id: item.cat_id,
    name: item.name,
    breed: item.breed || '',
    age_years: item.age_years || null,
  }));

  return NextResponse.json({ cats });
}
