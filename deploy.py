#!/usr/bin/python3
import os
import sys
import subprocess
import argparse
from pathlib import Path
from dotenv import load_dotenv
import shutil
import time
import datetime  # Added for timestamp generation
import yaml      # Added for YAML validation
import git

def check_helm_installation():
    """Check if Helm is installed, install if not"""
    if shutil.which('helm') is None:
        print("Helm not found. Installing Helm...")
        cmd = "curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash"
        if not execute_command(cmd):
            print("Failed to install Helm")
            sys.exit(1)
        print("Helm installed successfully")
    else:
        print("Helm is already installed")

def load_environment():
    """Load environment variables from .env file"""
    if not os.path.exists('.env'):
        print("Error: .env file not found")
        print("Please copy .env.example to .env and set your values")
        sys.exit(1)
    
    env_vars = {}
    with open('.env', 'r') as file:
        for line in file:
            # Ignora le righe vuote o i commenti
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()
    return env_vars


def process_yaml(file_path, env_vars):
    """Replace placeholders in YAML files with environment variables"""
    with open(file_path, 'r') as f:
        content = f.read()
        
    for key, value in env_vars.items():
        # Rimuovi apici solo all'inizio e alla fine della stringa
        if value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        elif value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        content = content.replace(f"${{{key}}}", value)
    return content

def execute_command(command, env=None, quiet=False):
    """Execute a shell command and capture its output"""
    try:
        result = subprocess.run(command, 
                              shell=True, 
                              check=True, 
                              capture_output=True, 
                              text=True,
                              env=env)  # Added env parameter
        if result.stdout and not quiet:
            print(result.stdout)
    except subprocess.CalledProcessError as e:
        if not quiet:
            print(f"Error executing command: {command}")
            print(e.stderr)
        return False
    return True

def confirm(prompt="Are you sure? [y/N]"):
    """Ask for user confirmation"""
    response = input(prompt).strip().lower()
    return response in ['y', 'yes']

def create_secrets(env_vars):
    """Create secrets from 00-secrets.yaml"""
    print("\n1. Creating secrets...")
    if not confirm("Do you want to create secrets? [y/N] "):
        print("Skipping secrets creation.")
        return

    secrets_path = "./preliminary/00-secrets.yaml"
    processed_secrets = process_yaml(secrets_path, env_vars)
    tmp_secrets_file = Path(f"/tmp/00-secrets.yaml")
    tmp_secrets_file.write_text(processed_secrets)

    if not execute_command(f"kubectl apply -f {tmp_secrets_file}"):
        print(f"Failed to apply {secrets_path}")
        sys.exit(1)
    tmp_secrets_file.unlink()
    print("Secrets created successfully.")

def install_metallb(env_vars):
    """Check and install MetalLB if not already installed"""
    print("\n2. Installing MetalLB...")
    if not confirm("Do you want to install MetalLB? [y/N] "):
        print("Skipping MetalLB installation.")
        return

    result = subprocess.run(
        "kubectl get namespace metallb-system",
        shell=True, capture_output=True, text=True
    )

    if result.returncode == 0:  # MetalLB is already installed
        print("MetalLB is already installed. Skipping installation.")
    else:
        print("MetalLB not found. Installing MetalLB...")
        if not execute_command("kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/v0.13.7/config/manifests/metallb-native.yaml"):
            print("Failed to install MetalLB.")
            sys.exit(1)

    print("Waiting for MetalLB pods to be ready...")
    ready = False
    for _ in range(10):  # Check readiness for up to 5 minutes
        time.sleep(30)
        pods = subprocess.run(
            "kubectl get pods -n metallb-system -o jsonpath='{.items[*].status.containerStatuses[*].ready}'",
            shell=True, capture_output=True, text=True
        )
        if "false" not in pods.stdout and "true" in pods.stdout:
            ready = True
            break
    if not ready:
        print("MetalLB pods are not ready. Please check the logs.")
        sys.exit(1)

    print("\nConfiguring MetalLB with 01-metallb-config.yaml...")
    metallb_config_path = "./preliminary/01-metallb-config.yaml"
    processed_content = process_yaml(metallb_config_path, env_vars)
    tmp_file = Path(f"/tmp/01-metallb-config.yaml")
    tmp_file.write_text(processed_content)

    if not execute_command(f"kubectl apply -f {tmp_file}"):
        print(f"Failed to apply {metallb_config_path}")
        sys.exit(1)
    tmp_file.unlink()

    print("MetalLB installed and configured successfully.")


def configure_storage(env_vars):
    """Configure storage from 02-storage.yaml"""
    print("\n3. Configuring storage...")
    if not confirm("Do you want to configure storage? [y/N] "):
        print("Skipping storage configuration.")
        return

    storage_path = "./preliminary/02-storage.yaml"
    processed_storage = process_yaml(storage_path, env_vars)
    tmp_storage_file = Path(f"/tmp/02-storage.yaml")
    tmp_storage_file.write_text(processed_storage)

    if not execute_command(f"kubectl apply -f {tmp_storage_file}"):
        print(f"Failed to apply {storage_path}")
        sys.exit(1)
    tmp_storage_file.unlink()
    print("Storage configured successfully.")

def install_traefik(env_vars):
    """Check and install/update Traefik in the cluster"""
    print("\n4. Installing Traefik...")
    if not confirm("Do you want to install/update Traefik? [y/N] "):
        print("Skipping Traefik installation/update.")
        return

    # Get user's home directory
    home_dir = os.path.expanduser("~")
    
    # Set up Helm environment variables
    helm_env = os.environ.copy()
    helm_env.update({
        'HELM_REPOSITORY_CONFIG': os.path.join(home_dir, '.config/helm/repositories.yaml'),
        'HELM_REPOSITORY_CACHE': os.path.join(home_dir, '.cache/helm/repository'),
        'HELM_CONFIG_HOME': os.path.join(home_dir, '.config/helm')
    })

    # Process the Traefik values file for variables
    values_file_path = "./preliminary/03-traefik-values.yaml"
    print(f"Processing {values_file_path} for variable substitution...")
    
    # Create a temporary file with processed values
    processed_values = process_yaml(values_file_path, env_vars)
    tmp_values_file = Path("/tmp/03-traefik-values.yaml")
    tmp_values_file.write_text(processed_values)

    # First, verify if Traefik repository exists
    print("Checking Traefik Helm repository status...")
    repo_check = subprocess.run(
        "helm repo list | grep traefik",
        shell=True, capture_output=True, text=True,
        env=helm_env
    )
    
    # Add repository if not found
    if repo_check.returncode != 0:
        print("Adding Traefik Helm repository...")
        if not execute_command("helm repo add traefik https://traefik.github.io/charts", env=helm_env, quiet=False):
            print("Failed to add Traefik Helm repository.")
            sys.exit(1)
    
    # Update all Helm repositories to get the latest versions
    print("Updating Helm repositories...")
    if not execute_command("helm repo update", env=helm_env, quiet=False):
        print("Failed to update Helm repositories.")
        sys.exit(1)

    # Check if Traefik is already installed
    result = subprocess.run(
        "kubectl get deployment traefik --namespace default",
        shell=True, capture_output=True, text=True,
        env=helm_env
    )

    try:
        if result.returncode != 0:  # Traefik not found
            print("Traefik not found in the cluster. Installing Traefik...")
            
            # Install Traefik using Helm with processed values file
            install_command = (
                f"helm install --values={tmp_values_file} traefik traefik/traefik "
                "--namespace default"
            )
            if not execute_command(install_command, env=helm_env, quiet=False):
                print("Failed to install Traefik.")
                sys.exit(1)

            print("Traefik installed successfully.")
        else:
            print("Traefik is already installed in the cluster.")
            if confirm("Do you want to update Traefik's configuration? [y/N] "):
                print("Updating Traefik configuration...")
                
                # Update Traefik using Helm upgrade with processed values file
                upgrade_command = (
                    f"helm upgrade --values={tmp_values_file} traefik traefik/traefik "
                    "--namespace default"
                )
                if not execute_command(upgrade_command, env=helm_env, quiet=False):
                    print("Failed to update Traefik configuration.")
                    sys.exit(1)
                    
                print("Traefik configuration updated successfully.")
            else:
                print("Skipping Traefik configuration update.")
    finally:
        # Clean up the temporary file
        if tmp_values_file.exists():
            tmp_values_file.unlink()

def configure_dashboard(env_vars):
    """Configure the Traefik dashboard"""
    print("\n5. Configuring Traefik dashboard...")
    if not confirm("Do you want to configure the Traefik dashboard? [y/N] "):
        print("Skipping Traefik dashboard configuration.")
        return

    dashboard_path = "./preliminary/04-traefik-dashboard.yaml"
    processed_dashboard = process_yaml(dashboard_path, env_vars)
    tmp_dashboard_file = Path(f"/tmp/04-traefik-dashboard.yaml")
    tmp_dashboard_file.write_text(processed_dashboard)

    if not execute_command(f"kubectl apply -f {tmp_dashboard_file}"):
        print(f"Failed to apply {dashboard_path}")
        sys.exit(1)
    tmp_dashboard_file.unlink()
    print("Traefik dashboard configured successfully.")

def init_infrastructure():
    """Initialize the base infrastructure"""
    print("You are about to initialize the base infrastructure:")
    print("------------------------------------------------")
    print("0. Check Helm installation")
    print("1. Create secrets (preliminary/00-secrets.yaml)")
    print("2. Install MetalLB (preliminary/01-metallb-config.yaml)")
    print("3. Configure storage (preliminary/02-storage.yaml)")
    print("4. Install Traefik (preliminary/03-traefik-values.yaml)")
    print("5. Configure Traefik dashboard (preliminary/04-traefik-dashboard.yaml)")
    print("------------------------------------------------")

    # Check Helm installation
    print("\nStep 0: Checking Helm installation...")
    check_helm_installation()
    
    
    env_vars = load_environment()

    print("\nEnvironment variables:")
    for key, value in sorted(env_vars.items()):
        if not key.startswith('_'):
            print(f"{key}={value}")

    create_secrets(env_vars)
    install_metallb(env_vars)
    configure_storage(env_vars)
    install_traefik(env_vars)
    configure_dashboard(env_vars)

    print("Infrastructure initialization completed.")

def deploy_manifest(manifest_path):
    """Deploy a specific manifest file"""
    if not os.path.exists(manifest_path):
        print(f"Error: File {manifest_path} not found")
        return False

    env_vars = load_environment()
    print(f"Applying {manifest_path}...")
    
    processed_content = process_yaml(manifest_path, env_vars)
    tmp_file = Path(f"/tmp/{Path(manifest_path).name}")
    tmp_file.write_text(processed_content)

    success = execute_command(f"kubectl apply -f {tmp_file}")
    tmp_file.unlink()
    
    return success

def deploy_all_manifests():
    """Deploy all manifests in the manifests directory"""
    manifests_dir = Path('manifests')
    if not manifests_dir.exists():
        print("Error: manifests directory not found")
        return False

    print("You are about to deploy the following manifests:")
    manifests = sorted(manifests_dir.glob('*.yaml'))
    for manifest in manifests:
        print(f"- {manifest}")

    env_vars = load_environment()

    print("\nEnvironment variables:")
    for key, value in sorted(env_vars.items()):
        if not key.startswith('_'):
            print(f"{key}={value}")

    if not confirm("Do you want to proceed with deploying ALL manifests? [y/N] "):
        print("Deployment cancelled.")
        return False

    for manifest in manifests:
        if not deploy_manifest(manifest):
            return False
    return True

def preview_file(file_path):
    """
    Preview how a file will look after variable substitution.
    This function loads environment variables and shows how the file would look
    with all variables replaced, without actually applying it.
    
    Args:
        file_path (str): Path to the YAML file to preview
    """
    try:
        # First verify the file exists
        if not os.path.exists(file_path):
            print(f"Error: File {file_path} not found")
            sys.exit(1)
            
        # Load environment variables
        print(f"Loading environment variables...")
        env_vars = load_environment()
        
        # Process the file
        print(f"\nPreviewing {file_path} with variable substitution:")
        print("=" * 80)  # Visual separator for better readability
        
        # Process the YAML file
        processed_content = process_yaml(file_path, env_vars)
        
        # Print the processed content
        print(processed_content)
        print("=" * 80)  # Visual separator at the end
        
        # Print which variables were replaced
        # This helps users understand what substitutions were made
        original_content = Path(file_path).read_text()
        replacements = []
        
        for key, value in env_vars.items():
            placeholder = f"${{{key}}}"
            if placeholder in original_content:
                replacements.append((key, value))
        
        if replacements:
            print("\nVariable substitutions made:")
            for key, value in replacements:
                print(f"  ${{{key}}} → {value}")
        else:
            print("\nNo variable substitutions were needed in this file.")
            
    except Exception as e:
        print(f"Error while previewing file: {str(e)}")
        sys.exit(1)

def create_production_files(output_dir="production-ready"):
    """
    Creates production-ready versions of all manifest files with variables substituted.
    This function processes all YAML files in the manifests directory and creates
    corresponding versions with all variables replaced from the environment file.
    
    Args:
        output_dir (str): Directory where production files will be created
        
    The function will:
    1. Create the output directory if it doesn't exist
    2. Clean any existing YAML files in that directory
    3. Process each manifest file, replacing variables
    4. Create a detailed summary including variable substitutions
    """
    try:
        print("\nStarting Fleet Production Process...")
        print("====================================")
        
        # First, load environment variables
        print("1. Loading environment variables...")
        env_vars = load_environment()
        
        # Create output directory if it doesn't exist
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)
        print(f"2. Ensuring output directory exists: {output_dir}/")
        
        # Clean existing files in the output directory
        print(f"3. Cleaning existing files in {output_dir}/...")
        file_count = 0
        for existing_file in output_path.glob("*.yaml"):
            existing_file.unlink()
            file_count += 1
        if file_count > 0:
            print(f"   Cleaned {file_count} existing files")
            
        # Get all manifest files
        manifests_dir = Path('manifests')
        if not manifests_dir.exists():
            print("Error: manifests directory not found")
            sys.exit(1)
            
        manifest_files = list(manifests_dir.glob('*.yaml'))
        if not manifest_files:
            print("Error: No manifest files found in manifests directory")
            sys.exit(1)
            
        print(f"\n4. Found {len(manifest_files)} manifest files to process...")
        
        # Keep track of which variables are used in which files
        file_var_usage = {}
        
        # Process each manifest file
        processed_count = 0
        for source_file in manifest_files:
            try:
                print(f"\nProcessing {source_file.name}...")
                
                # Create corresponding output file path
                output_file = output_path / source_file.name
                
                # Read original content to track variable usage
                original_content = source_file.read_text()
                used_vars = []
                for key in env_vars:
                    if f"${{{key}}}" in original_content:
                        used_vars.append(key)
                file_var_usage[source_file.name] = used_vars
                
                # Process the YAML file
                processed_content = process_yaml(str(source_file), env_vars)
                
                # Write the processed content to the output file
                output_file.write_text(processed_content)
                
                # Verify the written file is valid YAML
                try:
                    # Use load_all to support multiple YAML documents in one file
                    list(yaml.safe_load_all(processed_content))
                    print(f"✓ Successfully created: {output_file}")
                    processed_count += 1
                except yaml.YAMLError as e:
                    print(f"⚠ Error: Generated file {output_file.name} contains invalid YAML:")
                    print(str(e))
                    # Remove the invalid file
                    output_file.unlink()
                
            except Exception as e:
                print(f"✗ Error processing {source_file.name}: {str(e)}")
                continue
        
        # Create a summary file
        print("\n5. Generating fleet summary...")
        summary_file = output_path / "FLEET_SUMMARY.md"
        summary_content = [
            "# Fleet Deployment Summary",
            "",
            f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Processed Files:",
            ""
        ]
        
        # Add information about each processed file
        for source_file in manifest_files:
            output_file = output_path / source_file.name
            if output_file.exists():
                file_size = output_file.stat().st_size
                summary_content.append(f"- {source_file.name} ({file_size:,} bytes)")
                # Add variables used in this file
                if file_var_usage[source_file.name]:
                    summary_content.append("  Variables used in this file:")
                    for var in sorted(file_var_usage[source_file.name]):
                        summary_content.append(f"    - ${{{var}}} → {env_vars[var]}")
                else:
                    summary_content.append("  No variables used in this file")
                summary_content.append("")  # Add blank line between files
        
        # Get all used variables across all files
        all_used_vars = set()
        for vars_used in file_var_usage.values():
            all_used_vars.update(vars_used)
        
        # Add section for variable substitutions
        summary_content.extend([
            "## Environment Variable Substitutions:",
            "",
            "### Variables Used:",
            ""
        ])
        
        # Document which variables were used and their values
        for key in sorted(all_used_vars):
            if not key.startswith('_'):  # Skip internal variables
                summary_content.append(f"- ${{{key}}} → {env_vars[key]}")
        
        # Add section for unused variables
        unused_vars = set(env_vars.keys()) - all_used_vars
        if unused_vars:
            summary_content.extend([
                "",
                "### Unused Variables:",
                "The following variables were available but not used in any file:",
                ""
            ])
            for key in sorted(unused_vars):
                if not key.startswith('_'):  # Skip internal variables
                    summary_content.append(f"- ${{{key}}} → {env_vars[key]}")
        
        # Write the summary file
        summary_file.write_text('\n'.join(summary_content))
        
        print(f"""
Fleet creation complete!
======================
- Processed {processed_count} out of {len(manifest_files)} files
- Files are available in: {output_dir}/
- Summary file created: {output_dir}/FLEET_SUMMARY.md
""")
        
    except Exception as e:
        print(f"\nError creating production files: {str(e)}")
        sys.exit(1)

def show_changes(original_files, new_files):
    """
    Mostra le differenze tra i file originali e quelli nuovi, in stile Terraform.
    Evidenzia aggiunte, modifiche e rimozioni.
    """
    changes = {
        'add': [],      # File nuovi
        'modify': [],   # File modificati
        'remove': []    # File rimossi
    }
    
    # Controlla file nuovi e modificati
    for new_file in new_files:
        if new_file not in original_files:
            changes['add'].append(new_file)
        elif original_files[new_file] != new_files[new_file]:
            changes['modify'].append(new_file)
    
    # Controlla file rimossi
    for old_file in original_files:
        if old_file not in new_files:
            changes['remove'].append(old_file)
            
    # Stampa il resoconto delle modifiche in stile Terraform
    print("\nChanges to be applied:")
    print("=====================")
    
    if not any(changes.values()):
        print("\nNo changes detected. Your files are up to date!")
        return False
        
    if changes['add']:
        print("\n  \033[32m+ Add\033[0m:")
        for file in changes['add']:
            print(f"    + {file}")
            
    if changes['modify']:
        print("\n  \033[33m~ Modify\033[0m:")
        for file in changes['modify']:
            print(f"    ~ {file}")
            
    if changes['remove']:
        print("\n  \033[31m- Remove\033[0m:")
        for file in changes['remove']:
            print(f"    - {file}")
            
    return True

def create_production_files_and_push(output_dir="production-ready"):
    """
    Crea file di produzione e li push su una repository privata nel branch `main`,
    mostrando prima un piano delle modifiche in stile Terraform.
    Gestisce anche la rimozione di file non più presenti nei manifesti locali.
    """
    repo_path = Path("/tmp/private-repo")
    
    try:
        print("\nInitializing Fleet Production Process...")
        print("=====================================")

        # Carica variabili d'ambiente
        print("\n1. Loading environment variables...")
        env_vars = load_environment()
        
        # Verifica credenziali git
        private_repo_url = env_vars.get("PRIVATE_REPO_URL")
        git_username = env_vars.get("GIT_USERNAME")
        git_token = env_vars.get("GIT_TOKEN")

        if not all([private_repo_url, git_username, git_token]):
            print("Error: Missing git credentials in .env file.")
            print("Required variables: PRIVATE_REPO_URL, GIT_USERNAME, GIT_TOKEN")
            sys.exit(1)

        auth_repo_url = private_repo_url.replace("https://", f"https://{git_username}:{git_token}@")
        branch_name = "main"

        # Prepara directory di output
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True)

        # Clona repository per confronto
        print("\n2. Preparing change detection...")
        if repo_path.exists():
            shutil.rmtree(repo_path)
        repo = git.Repo.clone_from(auth_repo_url, repo_path)
        repo.git.checkout(branch_name)

        # Leggi i file esistenti nella repository remota
        existing_files = {
            yaml_file.name: yaml_file.read_text()
            for yaml_file in repo_path.glob("*.yaml")
        }

        # Processa i nuovi file dai manifesti locali
        print("\n3. Processing manifest files...")
        new_files = {}
        manifest_files = list(Path('manifests').glob('*.yaml'))
        
        # Lista dei file presenti nei manifesti locali
        local_manifest_names = set(source_file.name for source_file in manifest_files)
        
        # Identifica file da rimuovere (presenti nel repo ma non nei manifesti locali)
        files_to_remove = set(existing_files.keys()) - local_manifest_names
        
        for source_file in manifest_files:
            try:
                processed_content = process_yaml(str(source_file), env_vars)
                # Valida YAML
                try:
                    list(yaml.safe_load_all(processed_content))
                    new_files[source_file.name] = processed_content
                    print(f"✓ Validated: {source_file.name}")
                except yaml.YAMLError as e:
                    print(f"⚠ Warning: Invalid YAML in {source_file.name}:")
                    print(str(e))
            except Exception as e:
                print(f"✗ Error processing {source_file.name}: {str(e)}")

        # Mostra piano delle modifiche con rimozioni
        print("\n4. Generating change plan...")
        if not show_changes(existing_files, new_files):
            # Mostra comunque i file da rimuovere se ce ne sono
            if files_to_remove:
                print("\nFiles to be removed:")
                for file_to_remove in files_to_remove:
                    print(f"  - {file_to_remove}")
            else:
                print("\nNo changes to apply.")
                return

        # Chiedi conferma
        if not confirm("\nDo you want to apply these changes? [y/N] "):
            print("\nOperation cancelled.")
            return

        # Applica le modifiche
        print("\n5. Applying changes...")
        
        # Pulisci directory di output
        for file in output_path.glob("*.yaml"):
            file.unlink()
        
        # Scrivi i nuovi file
        for filename, content in new_files.items():
            (output_path / filename).write_text(content)
            print(f"✓ Created: {filename}")

        # Copia in repository e gestisci rimozioni
        print("\n6. Updating repository...")
        
        # Rimuovi i file non più presenti nei manifesti locali
        for file_to_remove in files_to_remove:
            file_path = repo_path / file_to_remove
            if file_path.exists():
                file_path.unlink()
                print(f"✓ Removed: {file_to_remove}")

        # Copia i nuovi file
        for file in output_path.glob("*.yaml"):
            shutil.copy(file, repo_path / file.name)

        # Git operations
        repo.git.add(all=True)
        if repo.index.diff("HEAD") or repo.untracked_files or files_to_remove:
            try:
                commit_message = f"Auto-update: {datetime.datetime.now().isoformat()}"
                if files_to_remove:
                    commit_message += f"\n\nRemoved files:\n" + "\n".join(files_to_remove)
                repo.git.commit(m=commit_message)
                repo.remotes.origin.push(refspec=f"{branch_name}:{branch_name}")
                print("✓ Changes pushed successfully")
            except git.exc.GitCommandError as e:
                print(f"Failed to push changes: {str(e)}")
                sys.exit(1)

        print(f"""
Fleet operation completed successfully!
====================================
- Files processed: {len(new_files)}
- Files removed: {len(files_to_remove)}
- Repository: {private_repo_url}
- Branch: {branch_name}
""")

    except Exception as e:
        print(f"\nError during operation: {str(e)}")
        sys.exit(1)
    finally:
        # Pulizia
        if repo_path.exists():
            shutil.rmtree(repo_path)

        
def main():
    parser = argparse.ArgumentParser(description='Deploy OpenCitations Infrastructure')
    parser.add_argument('-i', '--init', action='store_true', help='Initialize infrastructure')
    parser.add_argument('-p', '--preview', help='Preview a manifest or preliminary file with variable substitution')
    parser.add_argument('-f', '--fleet', action='store_true', help='Create production-ready versions of all manifests')
    parser.add_argument('manifest', nargs='?', help='Specific manifest file to deploy')
    
    args = parser.parse_args()

    if args.fleet:
        create_production_files_and_push()
    elif args.preview:
        preview_file(args.preview)
    elif args.init:
        init_infrastructure()
    elif args.manifest:
        deploy_manifest(args.manifest)
    else:
        deploy_all_manifests()

if __name__ == "__main__":
    main()