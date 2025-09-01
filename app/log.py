import time
from os import get_terminal_size

from loguru import logger
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel


def terminal_width():
    try:
        return get_terminal_size().columns
    except OSError:
        return 80


WIDTH = min(120, terminal_width() - 10)

console = Console()

print_stdout = True


def log_exception(exception):
    logger.exception(exception)


def print_banner(msg: str) -> None:
    if not print_stdout:
        return

    banner = f" {msg} ".center(WIDTH, "=")
    console.print()
    console.print(banner, style="bold")
    console.print()


def replace_html_tags(content: str):
    """
    Helper method to process the content before printing to markdown.
    """
    replace_dict = {
        "<file>": "[file]",
        "<class>": "[class]",
        "<func>": "[func]",
        "<method>": "[method]",
        "<code>": "[code]",
        "<original>": "[original]",
        "<patched>": "[patched]",
        "</file>": "[/file]",
        "</class>": "[/class]",
        "</func>": "[/func]",
        "</method>": "[/method]",
        "</code>": "[/code]",
        "</original>": "[/original]",
        "</patched>": "[/patched]",
    }
    for key, value in replace_dict.items():
        content = content.replace(key, value)
    return content


def print_acr(msg: str, desc="") -> None:
    if not print_stdout:
        return

    # Check if we should terminate on "Patch is not applicable"
    from app import config
    if config.stop_on_patch_not_applicable and "Patch is not applicable" in msg:
        config._should_terminate_on_patch_not_applicable = True
        print("\n🛑 Detected 'Patch is not applicable' - stopping execution as requested (simulating Ctrl+C)")

    msg = replace_html_tags(msg)
    markdown = Markdown(msg)

    name = "AutoCodeRover"
    if desc:
        title = f"{name} ({desc})"
    else:
        title = name

    panel = Panel(
        markdown,
        title=title,
        title_align="left",
        border_style="magenta",
        width=WIDTH,
    )
    console.print(panel)

    # After printing, check if we should terminate
    if config.stop_on_patch_not_applicable and config._should_terminate_on_patch_not_applicable:
        import sys
        import os
        print("Terminating process...")
        os._exit(1)  # Force immediate termination like Ctrl+C


def print_retrieval(msg: str, desc="") -> None:
    if not print_stdout:
        return

    msg = replace_html_tags(msg)
    markdown = Markdown(msg)

    name = "Context Retrieval Agent"
    if desc:
        title = f"{name} ({desc})"
    else:
        title = name

    panel = Panel(
        markdown,
        title=title,
        title_align="left",
        border_style="blue",
        width=WIDTH,
    )
    console.print(panel)


def print_patch_generation(msg: str) -> None:
    """Print a patch generation message with panel formatting"""
    from app import config
    
    console.print(Panel(msg, title="Patch Generation", style="bright_magenta"))
    
    # Debug: Always log when this function is called
    logger.info(f"print_patch_generation called. extract_patched_code = {config.extract_patched_code}")
    
    # Extract patched code if enabled
    if config.extract_patched_code:
        logger.info("Starting patched code extraction...")
        extract_and_save_patched_code(msg)


def extract_and_save_patched_code(msg: str) -> None:
    """Extract code between [patched] and [/patched] or <patched> and </patched> tags and save to file"""
    import re
    import os
    import json
    from pathlib import Path
    from app import config
    
    logger.info("extract_and_save_patched_code function called")
    logger.info(f"Message length: {len(msg)} characters")
    logger.info(f"Extract dir: {config.extract_patched_code_dir}")
    
    # Look for both [patched]...[/patched] and <patched>...</patched> sections
    patterns = [
        r'<patched>\s*(.*?)\s*</patched>',  # XML-style tags
        r'\[patched\]\s*(.*?)\s*\[/patched\]'  # Square bracket tags
    ]
    
    all_matches = []
    for pattern in patterns:
        matches = re.findall(pattern, msg, re.DOTALL)
        all_matches.extend(matches)
        logger.info(f"Pattern '{pattern}' found {len(matches)} sections")
    
    logger.info(f"Total found {len(all_matches)} patched sections")
    
    if all_matches:
        # Create output directory if it doesn't exist
        output_dir = Path(config.extract_patched_code_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created/verified directory: {output_dir}")
        
        # Extract namespace from <file> tag
        namespace = None
        file_pattern = r'<file>(.*?)</file>'
        file_matches = re.findall(file_pattern, msg)
        if file_matches:
            file_path = file_matches[0].strip()
            # Remove Source_Code/ prefix and .py suffix, convert to namespace
            if file_path.startswith('Source_Code/'):
                namespace_path = file_path[len('Source_Code/'):]
                if namespace_path.endswith('.py'):
                    namespace_path = namespace_path[:-3]
                # Convert path separators to dots for namespace
                namespace = namespace_path.replace('/', '.')
                logger.info(f"Extracted namespace: {namespace}")
        
        # Combine all patches for this issue into one file
        filename = f"test-{config.current_issue_number}.txt"
        filepath = output_dir / filename
        
        # Combine all patched code sections
        combined_code_sections = []
        
        for i, match in enumerate(all_matches):
            # Extract and clean the patched code
            patched_code = match.strip()
            
            # Remove any leading/trailing whitespace from each line while preserving structure
            lines = patched_code.split('\n')
            cleaned_lines = []
            for line in lines:
                # Only strip trailing whitespace to preserve indentation
                cleaned_lines.append(line.rstrip())
            
            # Join back and remove any leading/trailing empty lines
            cleaned_code = '\n'.join(cleaned_lines).strip()
            combined_code_sections.append(cleaned_code)
        
        # Join all sections with separator if multiple
        if len(combined_code_sections) > 1:
            final_code = '\n\n# ==========================================\n\n'.join(combined_code_sections)
        else:
            final_code = combined_code_sections[0] if combined_code_sections else ""
        
        # Save combined code to one file per issue
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(final_code)
            print(f"✅ Extracted patched code saved to: {filepath}")
            logger.info(f"Successfully saved patched code to: {filepath}")
            logger.info(f"Code preview: {final_code[:100]}...")
        except Exception as e:
            print(f"❌ Error saving patched code to {filepath}: {e}")
            logger.error(f"Error saving patched code to {filepath}: {e}")
        
        # Save each section to completion.jsonl file if namespace is available
        for i, match in enumerate(all_matches):
            patched_code = match.strip()
            
            if namespace:
                try:
                    jsonl_filepath = output_dir / "completion.jsonl"
                    
                    # Extract ALL content from patched section (no filtering)
                    completion_code = patched_code.strip()
                    
                    # Create the JSON object
                    json_obj = {
                        "namespace": namespace,
                        "completion": completion_code
                    }
                    
                    # Append to JSONL file
                    with open(jsonl_filepath, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(json_obj) + '\n')
                    
                    print(f"✅ Completion saved to: {jsonl_filepath}")
                    logger.info(f"Successfully saved completion to: {jsonl_filepath}")
                    logger.info(f"Namespace: {namespace}")
                    logger.info(f"Completion preview: {completion_code[:50]}...")
                    
                except Exception as e:
                    print(f"❌ Error saving completion to JSONL: {e}")
                    logger.error(f"Error saving completion to JSONL: {e}")
            else:
                logger.warning("No namespace found, skipping JSONL generation")
                
    else:
        print("ℹ️  No [patched] or <patched> section found in the patch generation message")
        logger.info("No [patched] or <patched> section found in the message")
        # Debug: show a preview of the message to help troubleshoot
        logger.debug(f"Message preview (first 500 chars): {msg[:500]}")
        # Check if there are any brackets at all
        if ('<' in msg and '>' in msg) or ('[' in msg and ']' in msg):
            logger.debug("Message contains brackets/tags - checking for alternative patterns")
            # Show all bracket patterns found
            bracket_matches = re.findall(r'<[^>]+>|\[[^\]]+\]', msg)
            logger.debug(f"Found bracket/tag patterns: {bracket_matches[:10]}")  # Limit to first 10
        else:
            logger.debug("No brackets/tags found in message")


def print_issue(content: str) -> None:
    if not print_stdout:
        return

    title = "Issue description"
    panel = Panel(
        content,
        title=title,
        title_align="left",
        border_style="red",
    )
    console.print(panel)


def print_reproducer(msg: str, desc="") -> None:
    if not print_stdout:
        return

    markdown = Markdown(msg)

    name = "Reproducer Test Generation"
    if desc:
        title = f"{name} ({desc})"
    else:
        title = name

    panel = Panel(
        markdown,
        title=title,
        title_align="left",
        border_style="green",
        width=WIDTH,
    )
    console.print(panel)


def print_exec_reproducer(msg: str, desc="") -> None:
    if not print_stdout:
        return

    markdown = Markdown(msg)

    name = "Reproducer Execution Result"
    if desc:
        title = f"{name} ({desc})"
    else:
        title = name

    panel = Panel(
        markdown,
        title=title,
        title_align="left",
        border_style="blue",
        width=WIDTH,
    )
    console.print(panel)


def print_review(msg: str, desc="") -> None:
    if not print_stdout:
        return

    markdown = Markdown(msg)

    name = "Review"
    if desc:
        title = f"{name} ({desc})"
    else:
        title = name

    panel = Panel(
        markdown,
        title=title,
        title_align="left",
        border_style="purple",
        width=WIDTH,
    )
    console.print(panel)


def log_and_print(msg):
    logger.info(msg)
    if print_stdout:
        console.print(msg)


def log_and_cprint(msg, **kwargs):
    logger.info(msg)
    if print_stdout:
        console.print(msg, **kwargs)


def log_and_always_print(msg):
    """
    A mode which always print to stdout, no matter what.
    Useful when running multiple tasks and we just want to see the important information.
    """
    logger.info(msg)
    # always include time for important messages
    t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    console.print(f"\n[{t}] {msg}")


def print_with_time(msg):
    """
    Print a msg to console with timestamp.
    """
    t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    console.print(f"\n[{t}] {msg}")
