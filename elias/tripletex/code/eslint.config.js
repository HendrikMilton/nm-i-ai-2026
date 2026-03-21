import tsParser from '@typescript-eslint/parser';
import tsPlugin from '@typescript-eslint/eslint-plugin';
import unusedImports from 'eslint-plugin-unused-imports';
import preferArrow from 'eslint-plugin-prefer-arrow-functions';

export default [
    {
        files: ['src/**/*.ts'],
        languageOptions: {
            parser: tsParser,
            ecmaVersion: 'latest',
            sourceType: 'module',
        },
        plugins: {
            '@typescript-eslint': tsPlugin,
            'unused-imports': unusedImports,
            'prefer-arrow-functions': preferArrow,
        },
        rules: {
            indent: ['error', 4, { SwitchCase: 1 }],
            'linebreak-style': ['error', 'unix'],
            quotes: ['error', 'single'],
            semi: ['error', 'always'],
            'quote-props': ['error', 'as-needed'],
            curly: ['error', 'all'],
            'brace-style': ['error', '1tbs'],
            '@typescript-eslint/no-unused-vars': 'off',
            'unused-imports/no-unused-imports': 'error',
            'unused-imports/no-unused-vars': [
                'error',
                { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
            ],
            '@typescript-eslint/no-explicit-any': 'off',
            'prefer-arrow-functions/prefer-arrow-functions': [
                'error',
                {
                    allowNamedFunctions: false,
                    classPropertiesAllowed: false,
                    disallowPrototype: false,
                    returnStyle: 'unchanged',
                    singleReturnOnly: false,
                },
            ],
        },
    },
    {
        ignores: ['dist/**', 'node_modules/**'],
    },
];
