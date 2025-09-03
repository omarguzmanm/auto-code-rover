"""
Values of global configuration variables.
"""

# Overall output directory for results
output_dir: str = ""

# Max number of times context retrieval and all is tried
overall_retry_limit: int = 1

# upper bound of the number of conversation rounds for the agent
conv_round_limit: int = 1

# whether to perform sbfl
enable_sbfl: bool = False

# whether to perform our own validation
enable_validation: bool = False

# whether to do angelic debugging
enable_angelic: bool = False

# whether to do perfect angelic debugging
enable_perfect_angelic: bool = False


# A special mode to only save SBFL result and exit
only_save_sbfl_result: bool = False

# A special mode to only generate reproducer tests and exit
only_reproduce: bool = False

# A special mode to only evaluate a reproducer test
only_eval_reproducer: bool = False

# Experimental mode to add reproducer and reviewer into the workflow
reproduce_and_review: bool = False

# Stop after the first successful patch generation
stop_after_first_patch: bool = False

# Stop immediately when patch is not applicable
stop_on_patch_not_applicable: bool = False

# Extract patched code from patch generation panels
extract_patched_code: bool = False

# Directory to save extracted patched code
extract_patched_code_dir: str = "results-ebc"

# Counter for extracted patches (starts at 0, will be incremented)
_extracted_patch_counter: int = 0

# Issue number for unique filenames (set externally)
current_issue_number: int = 1

# Current issue file path (set externally)
current_issue_file: str = ""

# Global flag set when patch is not applicable (internal use)
_should_terminate_on_patch_not_applicable: bool = False

# timeout for test cmd execution, currently set to 5 min
test_exec_timeout: int = 300

models: list[str] = []

backup_model = ["gpt-4o-2024-05-13"]

disable_angelic: bool = False
