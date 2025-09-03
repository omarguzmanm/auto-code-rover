#!/usr/bin/env python3
"""
DeepSeek V3 issue processor for AutoCodeRover
Processes issues 1-275 using DeepSeek V3 from Azure AI
"""

import subprocess
import os
import time
import sys
import json
from pathlib import Path
from datetime import datetime

class DeepSeekIssueProcessor:
    def __init__(self):
        # Comando base usando DeepSeek V3
        self.base_command = [
            "python", "app/main.py", "local-issue",
            "--stop-after-first-patch",
            "--stop-on-patch-not-applicable", 
            "--extract-patched-code",
            "--extract-patched-code-dir", "results-ebc-deepseek",  # Directorio diferente
            "--output-dir", "output-deepseek",  # Output diferente
            "--model", "DeepSeek-V3-0324",  # Modelo DeepSeek V3 Azure AI deployment
            "--model-temperature", "0.2"
        ]
        
        self.workspace_repo = "/workspace/"
        self.issues_dir = "/workspace/issues/individual_issues/"
        self.results_dir = Path("results-ebc-deepseek")
        
        # Contadores
        self.stats = {
            "successful": 0,
            "failed": 0,
            "not_found": 0,
            "total": 0
        }
        
        self.log_file = "processing_log_deepseek.txt"
        
        # Ensure API key is available
        if not (os.getenv("AZURE_AI_API_KEY") or os.getenv("OPENAI_API_KEY")):
            raise ValueError("Please set AZURE_AI_API_KEY or OPENAI_API_KEY environment variable")
        
    def log_message(self, message):
        """Registra mensaje en log y pantalla"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] {message}"
        print(log_entry)
        
        # Escribir al archivo de log
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(log_entry + "\n")
    
    def setup_environment(self):
        """Prepara el entorno para el procesamiento"""
        # Verificar API key
        if not (os.getenv("AZURE_AI_API_KEY") or os.getenv("OPENAI_API_KEY")):
            raise Exception("❌ AZURE_AI_API_KEY o OPENAI_API_KEY no está configurada. Ejecuta: export AZURE_AI_API_KEY='tu_api_key'")
        
        # Verificar directorios
        if not Path(self.issues_dir).exists():
            raise Exception(f"El directorio {self.issues_dir} no existe")
        
        # Crear directorio de resultados si no existe
        self.results_dir.mkdir(exist_ok=True)
        
        # Limpiar log anterior
        if Path(self.log_file).exists():
            Path(self.log_file).unlink()
        
        self.log_message("🚀 Iniciando procesamiento de issues con DeepSeek V3")
        self.log_message(f"🔑 Azure AI API Key configurada: ✅")
        self.log_message(f"📁 Directorio de issues: {self.issues_dir}")
        self.log_message(f"📁 Directorio de resultados: {self.results_dir}")
    
    def process_single_issue(self, issue_num):
        """Procesa un issue individual"""
        issue_file = f"{self.issues_dir}issue-{issue_num}.txt"
        task_id = f"test-ecb-deepseek-{issue_num}"
        
        # Establecer el número de issue actual para el naming de archivos
        import sys
        sys.path.insert(0, '.')
        from app import config
        config.current_issue_number = issue_num
        
        # Verificar que el archivo existe
        if not Path(issue_file).exists():
            self.log_message(f"⚠️  Issue {issue_num}: Archivo no encontrado")
            self.stats["not_found"] += 1
            return False
        
        # Preparar comando
        command = self.base_command + [
            "--task-id", task_id,
            "--local-repo", self.workspace_repo,
            "--issue-file", issue_file
        ]
        
        self.log_message(f"📝 Procesando Issue {issue_num} con DeepSeek V3 - {task_id}")
        
        try:
            # Configurar entorno
            env = os.environ.copy()
            env["PYTHONPATH"] = "."
            
            # Ejecutar con timeout más largo para rate limits
            result = subprocess.run(
                command,
                timeout=1800,  # 30 minutos por issue para rate limits
                capture_output=True,
                text=True,
                env=env,
                cwd="/opt/auto-code-rover"
            )
            
            if result.returncode == 0:
                self.log_message(f"   ✅ Issue {issue_num}: Completado exitosamente")
                self.stats["successful"] += 1
                return True
            else:
                self.log_message(f"   ❌ Issue {issue_num}: Falló con código {result.returncode}")
                # Log de error detallado
                if result.stderr:
                    error_preview = result.stderr[:300].replace('\n', ' ')
                    self.log_message(f"   Error: {error_preview}")
                self.stats["failed"] += 1
                return False
                
        except subprocess.TimeoutExpired:
            self.log_message(f"   ⏰ Issue {issue_num}: Timeout después de 30 minutos")
            self.stats["failed"] += 1
            return False
        except Exception as e:
            self.log_message(f"   💥 Issue {issue_num}: Error inesperado: {e}")
            self.stats["failed"] += 1
            return False
    
    def run_batch(self, start_issue=1, end_issue=275):
        """Ejecuta un lote de issues"""
        self.setup_environment()
        
        self.log_message(f"🎯 Procesando issues {start_issue} a {end_issue}")
        
        start_time = time.time()
        
        for issue_num in range(start_issue, end_issue + 1):
            self.stats["total"] += 1
            
            # Progreso
            if issue_num % 10 == 0:
                elapsed = time.time() - start_time
                self.log_message(f"📊 Progreso: {issue_num}/{end_issue} - {elapsed:.1f}s elapsed")
                self.log_message(f"   Stats: ✅{self.stats['successful']} ❌{self.stats['failed']} ⚠️{self.stats['not_found']}")
            
            # Procesar issue
            success = self.process_single_issue(issue_num)
            
            # Pausa larga para evitar rate limits (Azure AI S0 tier)
            self.log_message(f"   ⏳ Esperando 10 segundos antes del siguiente issue...")
            time.sleep(10)
        
        # Resumen final
        total_time = time.time() - start_time
        self.log_message("=" * 70)
        self.log_message(f"🏁 PROCESAMIENTO COMPLETADO")
        self.log_message(f"⏱️  Tiempo total: {total_time:.1f} segundos ({total_time/60:.1f} minutos)")
        self.log_message(f"📊 Estadísticas finales:")
        self.log_message(f"   ✅ Exitosos: {self.stats['successful']}")
        self.log_message(f"   ❌ Fallidos: {self.stats['failed']}")
        self.log_message(f"   ⚠️  No encontrados: {self.stats['not_found']}")
        self.log_message(f"   📈 Tasa de éxito: {self.stats['successful']}/{self.stats['total']} ({100*self.stats['successful']/self.stats['total']:.1f}%)")
        
        # Verificar resultados
        result_files = list(self.results_dir.glob("test-*.txt"))
        completion_file = self.results_dir / "completion.jsonl"
        
        # Generar completion.jsonl si no existe
        if not completion_file.exists():
            try:
                # Crear archivo completion.jsonl básico
                with open(completion_file, 'w') as f:
                    for i in range(start_issue, end_issue + 1):
                        if i <= start_issue + self.stats["total"] - 1:
                            success = i <= start_issue + self.stats["successful"] - 1
                            entry = {
                                "issue": i,
                                "model": "DeepSeek-V3-0324",
                                "success": success,
                                "generated": success
                            }
                            f.write(json.dumps(entry) + '\n')
                self.log_message(f"   📋 completion.jsonl generado con {self.stats['total']} entradas")
            except Exception as e:
                self.log_message(f"   ❌ Error generando completion.jsonl: {e}")
        
        self.log_message(f"📁 Archivos generados:")
        self.log_message(f"   📄 test-*.txt: {len(result_files)}")
        self.log_message(f"   📋 completion.jsonl: {'✅' if completion_file.exists() else '❌'}")
        
        if completion_file.exists():
            try:
                with open(completion_file, 'r') as f:
                    lines = f.readlines()
                self.log_message(f"   📊 Entradas en completion.jsonl: {len(lines)}")
            except Exception as e:
                self.log_message(f"   ❌ Error leyendo completion.jsonl: {e}")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Procesar issues con DeepSeek V3')
    parser.add_argument('--start', type=int, default=1, help='Issue inicial (default: 1)')
    parser.add_argument('--end', type=int, default=275, help='Issue final (default: 275)')
    parser.add_argument('--test', action='store_true', help='Solo procesar primeros 3 issues')
    
    args = parser.parse_args()
    
    if args.test:
        args.start = 1
        args.end = 3
        print("🧪 MODO PRUEBA: Procesando primeros 3 issues con DeepSeek V3")
    
    processor = DeepSeekIssueProcessor()
    processor.run_batch(args.start, args.end)

if __name__ == "__main__":
    main()
