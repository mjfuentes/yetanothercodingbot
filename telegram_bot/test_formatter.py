#!/usr/bin/env python3
"""
Test script for response formatter
"""

from formatter import ResponseFormatter, format_telegram_response


def test_path_formatting():
    """Test file path highlighting"""
    formatter = ResponseFormatter()

    test_cases = [
        (
            "The groovetherapy repository has been deleted from /Users/matifuentes/Workspace/groovetherapy",
            "Should highlight absolute path",
        ),
        ("I modified telegram_bot/main.py to add the formatter", "Should highlight relative path with extension"),
        ("Check ~/projects/myapp for the config", "Should highlight home directory path"),
    ]

    print("=" * 60)
    print("PATH FORMATTING TESTS")
    print("=" * 60)

    for text, description in test_cases:
        print(f"\n{description}")
        print(f"Input:  {text}")
        result = formatter.format_response(text)
        print(f"Output: {result}")


def test_repository_formatting():
    """Test repository name highlighting"""
    formatter = ResponseFormatter()

    test_cases = [
        ("Do you want to delete groovetherapy?", "Should highlight repository name"),
        ("The agentlab repository contains the bot code", "Should bold repository references"),
        ("Working on myproject project now", "Should highlight project references"),
    ]

    print("\n" + "=" * 60)
    print("REPOSITORY FORMATTING TESTS")
    print("=" * 60)

    for text, description in test_cases:
        print(f"\n{description}")
        print(f"Input:  {text}")
        result = formatter.format_response(text)
        print(f"Output: {result}")


def test_list_formatting():
    """Test list formatting"""
    formatter = ResponseFormatter()

    text = """Here are the steps:
* First step
* Second step
* Third step

Then continue with more text."""

    print("\n" + "=" * 60)
    print("LIST FORMATTING TEST")
    print("=" * 60)
    print(f"Input:\n{text}")
    result = formatter.format_response(text)
    print(f"\nOutput:\n{result}")


def test_code_block_formatting():
    """Test code block formatting"""
    formatter = ResponseFormatter()

    text = """Here's the code:```python
def hello():
    print("world")
```That's it!"""

    print("\n" + "=" * 60)
    print("CODE BLOCK FORMATTING TEST")
    print("=" * 60)
    print(f"Input:\n{text}")
    result = formatter.format_response(text)
    print(f"\nOutput:\n{result}")


def test_complete_response():
    """Test a complete realistic response"""
    formatter = ResponseFormatter()

    text = """Done. The groovetherapy repository has been permanently deleted from /Users/matifuentes/Workspace/groovetherapy.

If this repository was connected to a remote (GitHub, GitLab, etc.), you'll need to delete it there separately through the platform's web interface.

Next steps:
* Check your GitHub account
* Remove any related configurations
* Update your local bookmarks"""

    print("\n" + "=" * 60)
    print("COMPLETE RESPONSE TEST")
    print("=" * 60)
    print(f"Input:\n{text}")
    result = formatter.format_response(text)
    print(f"\nOutput:\n{result}")


def test_chunking():
    """Test message chunking"""
    # Create a long message
    long_text = "This is a test. " * 300

    print("\n" + "=" * 60)
    print("CHUNKING TEST")
    print("=" * 60)
    print(f"Input length: {len(long_text)} characters")

    chunks = format_telegram_response(long_text, max_length=4096)
    print(f"Number of chunks: {len(chunks)}")
    for i, chunk in enumerate(chunks):
        print(f"Chunk {i + 1} length: {len(chunk)}")


if __name__ == "__main__":
    test_path_formatting()
    test_repository_formatting()
    test_list_formatting()
    test_code_block_formatting()
    test_complete_response()
    test_chunking()

    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETE")
    print("=" * 60)
