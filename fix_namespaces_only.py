#!/usr/bin/env python3
"""
Fix namespaces in existing completion.jsonl files by reading the original issue files
and extracting the correct namespace from **Namespace:** pattern.
Does NOT call the model again, just fixes the namespace field.
"""

import json
import re
import os
from pathlib import Path

def extract_namespace_from_issue(issue_file_path):
    """Extract namespace from issue file"""
    try:
        with open(issue_file_path, 'r', encoding='utf-8') as f:
            issue_content = f.read()
            # Look for **Namespace:** pattern in the issue
            namespace_pattern = r'\*\*Namespace:\*\*\s*`([^`]+)`'
            namespace_match = re.search(namespace_pattern, issue_content)
            if not namespace_match:
                # Try alternative pattern without backticks
                namespace_pattern = r'\*\*Namespace:\*\*\s*([^\n\r]+)'
                namespace_match = re.search(namespace_pattern, issue_content)
            if namespace_match:
                namespace = namespace_match.group(1).strip()
                return namespace
    except Exception as e:
        print(f"Error reading {issue_file_path}: {e}")
    return None

def get_issue_number_from_filename(filename):
    """Extract issue number from test-N.txt filename"""
    match = re.search(r'test-(\d+)\.txt', filename)
    if match:
        return int(match.group(1))
    return None

def fix_namespaces_in_results(results_dir, issues_dir):
    """Fix namespaces in completion.jsonl file using issue files"""
    completion_file = Path(results_dir) / "completion.jsonl"
    if not completion_file.exists():
        print(f"No completion.jsonl found in {results_dir}")
        return
    
    # Read all existing entries
    entries = []
    with open(completion_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            if line.strip():
                try:
                    entry = json.loads(line)
                    entries.append((line_num, entry))
                except json.JSONDecodeError as e:
                    print(f"Error parsing line {line_num}: {e}")
    
    print(f"Found {len(entries)} entries in {completion_file}")
    
    # Get mapping of test files to issue numbers
    test_files_dir = Path(results_dir)
    test_files = list(test_files_dir.glob("test-*.txt"))
    
    # Create mapping from issue number to namespace
    issue_to_namespace = {}
    for issue_num in range(1, 276):
        issue_file = Path(issues_dir) / f"issue-{issue_num}.txt"
        if issue_file.exists():
            namespace = extract_namespace_from_issue(issue_file)
            if namespace:
                issue_to_namespace[issue_num] = namespace
    
    print(f"Found namespaces for {len(issue_to_namespace)} issues")
    
    # The completion.jsonl entries correspond to test-N.txt files
    # We need to map them back to issue numbers
    fixed_entries = []
    fixes_applied = 0
    
    # Group entries by their position to map to test file numbers
    # Assuming the entries are in order and correspond to test-1.txt, test-2.txt, etc.
    current_issue = 1
    
    for line_num, entry in entries:
        original_namespace = entry.get("namespace", "unknown")
        
        # Try to find the corresponding issue number
        # Method 1: Use sequential numbering (most likely)
        if current_issue in issue_to_namespace:
            correct_namespace = issue_to_namespace[current_issue]
            if correct_namespace != original_namespace:
                entry["namespace"] = correct_namespace
                fixes_applied += 1
                print(f"Fixed issue {current_issue}: '{original_namespace}' -> '{correct_namespace}'")
        
        fixed_entries.append(entry)
        current_issue += 1
    
    # Write the fixed entries back to completion.jsonl
    backup_file = completion_file.with_suffix('.jsonl.backup')
    completion_file.rename(backup_file)
    print(f"Created backup: {backup_file}")
    
    with open(completion_file, 'w', encoding='utf-8') as f:
        for entry in fixed_entries:
            f.write(json.dumps(entry) + '\n')
    
    print(f"✅ Fixed {fixes_applied} namespaces in {completion_file}")
    print(f"📁 Backup saved as {backup_file}")

def main():
    # Fix DeepSeek results
    # deepseek_results_dir = "/opt/auto-code-rover/results-ebc-deepseek-old-namespaces"
    # if Path(deepseek_results_dir).exists():
    #     print("🔧 Fixing DeepSeek results...")
    #     fix_namespaces_in_results(deepseek_results_dir, "/workspace/issues/individual_issues")
    # else:
    #     print(f"DeepSeek results directory not found: {deepseek_results_dir}")
    
    # Fix GPT results if they exist
    # gpt_results_dir = "/opt/auto-code-rover/results-ebc-gpt/test"
    # if Path(gpt_results_dir).exists() and Path(gpt_results_dir, "completion.jsonl").exists():
    #     print("\n🔧 Fixing GPT results...")
    #     fix_namespaces_in_results(gpt_results_dir, "/workspace/issues/individual_issues")
    # else:
    #     print(f"GPT results completion.jsonl not found in: {gpt_results_dir}")

    # Fix Claude results
    claude_results_dir = "/opt/auto-code-rover/results-ebc-claude"
    if Path(claude_results_dir).exists() and Path(claude_results_dir, "completion.jsonl").exists():
        print("\n🔧 Fixing Claude results...")
        fix_namespaces_in_results(claude_results_dir, "/workspace/issues/individual_issues")
    else:
        print(f"Claude results completion.jsonl not found in: {claude_results_dir}")

if __name__ == "__main__":
    main()
