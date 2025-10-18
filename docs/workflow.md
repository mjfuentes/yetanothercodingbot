# Workflow Enforcement System

## Overview

This bot now enforces a strict workflow for all coding tasks to ensure code quality, testing, and proper version control practices.

## Workflow Requirements

For **ALL** coding tasks, the following workflow is automatically enforced:

1. **Pre-commit Hooks** - Code formatting, linting, and security checks
2. **Testing** - All tests must pass before committing
3. **Git Commits** - All changes must be committed with descriptive messages

## How It Works

### 1. Pre-commit Hooks

The `.pre-commit-config.yaml` file defines hooks that run automatically:

- **Code Formatting**: Black (Python code formatter)
- **Import Sorting**: isort (organizes imports)
- **Linting**: Ruff (fast Python linter)
- **Security**: Bandit (security vulnerability scanner)
- **File Checks**: Trailing whitespace, EOF, YAML/JSON validation
- **Test Coverage**: Verifies tests exist for code changes
- **Workflow Reminder**: Displays workflow status

### 2. Testing Requirements

- Tests are **required** for all Python code changes
- Tests must be in `test_*.py` or `*_test.py` files
- Tests must pass before commits are allowed
- Use pytest: `python3 -m pytest -v --tb=short`

### 3. Commit Requirements

- All changes must be committed to git
- Commits include:
  - Descriptive message based on task
  - Automated workflow enforcement notice
  - All staged and unstaged changes

## Workflow Enforcer Module

The `workflow_enforcer.py` module provides:

```python
from workflow_enforcer import WorkflowEnforcer

enforcer = WorkflowEnforcer(workspace_path)
success, message = enforcer.enforce_workflow(task_description)
```

### Key Methods

- `get_changed_files()` - Lists modified Python files
- `has_uncommitted_changes()` - Checks for uncommitted work
- `run_tests()` - Executes pytest on the codebase
- `run_pre_commit_hooks()` - Runs all pre-commit checks
- `create_commit(message)` - Creates a git commit
- `enforce_workflow(task_description)` - Runs complete workflow

## Integration with Claude Sessions

The `ClaudeInteractiveSession` class automatically enforces workflow:

```python
session = ClaudeInteractiveSession(
    workspace=Path("/path/to/repo"),
    model="sonnet",
    enforce_workflow=True  # Default: enabled
)
```

When a coding task completes:
1. Claude receives workflow requirements in the prompt
2. After code execution, workflow enforcer runs automatically
3. Results include workflow enforcement report

## Disabling Workflow Enforcement

To disable for specific tasks (not recommended):

```python
# In main.py when creating the pool
claude_pool = ClaudeSessionPool(enforce_workflow=False)

# Or for individual sessions
session = ClaudeInteractiveSession(workspace, enforce_workflow=False)
```

## Setup Instructions

### Install Pre-commit

```bash
pip install pre-commit
cd /path/to/agentlab
pre-commit install
```

### Install Testing Tools

```bash
pip install pytest pytest-asyncio pytest-cov
```

### Manual Testing

Run pre-commit hooks manually:
```bash
pre-commit run --all-files
```

Run tests manually:
```bash
cd telegram_bot
python3 -m pytest -v --tb=short
```

## Example Workflow

When you ask the bot to "add a new feature":

1. **Bot receives request** → Creates background task
2. **Claude executes code** → Writes/modifies Python files
3. **Pre-commit hooks run** → Formatting, linting, security
4. **Tests execute** → Validates code works correctly
5. **Git commit created** → Changes are committed
6. **User notification** → Report includes workflow status

Example notification:
```
Task Complete (#abc123)

Added user authentication feature

Result:
Created auth.py with login/logout functions
Updated main.py to integrate authentication

============================================================
WORKFLOW ENFORCEMENT
============================================================

=== Pre-commit Hooks ===
Pre-commit hooks passed

=== Running Tests ===
Tests passed:
test_auth.py::test_login PASSED
test_auth.py::test_logout PASSED

=== Creating Commit ===
Commit created successfully:
[main abc1234] Added user authentication feature

Workflow completed successfully!
```

## Troubleshooting

### Pre-commit Hooks Fail
- Review the error messages
- Fix formatting/linting issues
- Run `pre-commit run --all-files` to test

### Tests Fail
- Check test output for failures
- Fix the code or tests
- Run `pytest -v` to debug

### Commit Fails
- Ensure you're in a git repository
- Check for git conflicts
- Verify git is configured properly

## Benefits

1. **Consistent Code Quality** - All code follows same standards
2. **Automatic Testing** - No untested code reaches main branch
3. **Version Control** - All changes tracked in git
4. **Security** - Automated security scanning
5. **Documentation** - Commit messages describe changes
6. **Reliability** - Reduce bugs through testing

## Configuration Files

- `.pre-commit-config.yaml` - Pre-commit hook configuration
- `telegram_bot/workflow_enforcer.py` - Workflow enforcement logic
- `telegram_bot/claude_interactive.py` - Integration with Claude sessions
- `WORKFLOW.md` - This documentation

## Best Practices

1. Write tests **before** asking bot to code
2. Keep commits focused and atomic
3. Review workflow enforcement reports
4. Address failures promptly
5. Update tests when changing functionality

## Future Enhancements

Potential additions:
- Code coverage reporting
- Integration with CI/CD pipelines
- Automated PR creation
- Test generation suggestions
- Performance benchmarking
