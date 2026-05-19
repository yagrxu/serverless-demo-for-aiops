export default {
  testEnvironment: 'node',
  roots: ['<rootDir>/test'],
  testMatch: ['**/*.test.ts'],
  transform: { '^.+\\.tsx?$': 'ts-jest' },
  testTimeout: 60000,
  reporters: ['default', ['jest-junit', { outputDirectory: '.', outputName: 'junit.xml' }]],
};
