# Contributing to OpenAI Proxy

Thanks for your interest in contributing to the OpenAI Proxy project! Here's how you can help.

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR-USERNAME/openai-proxy.git`
3. Create a branch for your changes: `git checkout -b your-feature-name`

## Setting Up Development Environment

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Copy the example environment file:
   ```
   cp .env-example .env
   ```

3. Edit the `.env` file with your API keys and settings

## Making Changes

1. Make your changes in your branch
2. Write or update tests to cover your changes
3. Run the tests to make sure everything works:
   ```
   pytest
   ```
4. Make sure your code follows the project's style guidelines

## Submitting Your Changes

1. Push your changes to your fork: `git push origin your-feature-name`
2. Create a pull request from your fork to the main repository
3. In your pull request, describe the changes and why they should be included

## Code Style

- Use Python type hints wherever possible
- Follow PEP 8 style guidelines
- Add docstrings to functions and classes
- Keep functions small and focused on a single task

## Testing

- Add tests for any new features or bug fixes
- Ensure all tests pass before submitting your pull request
- Include both unit tests and integration tests when appropriate

## Reporting Bugs

If you find a bug, please create an issue with:

1. A clear description of the bug
2. Steps to reproduce it
3. Expected vs. actual behavior
4. Environment information (OS, Python version, etc.)

## Feature Requests

For feature requests, please create an issue that describes:

1. The problem you're trying to solve
2. Why it's important
3. Your proposed solution

## License

By contributing, you agree that your contributions will be licensed under the project's Apache License 2.0. 