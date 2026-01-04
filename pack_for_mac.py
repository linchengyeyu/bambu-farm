import os
import zipfile

def pack_project():
    # 压缩包名称
    zip_filename = "bambu_farm_deploy.zip"
    
    # 需要打包的基础目录
    base_dir = "backend"
    
    # 需要排除的目录和文件
    excludes = {
        'venv', '__pycache__', '.git', '.idea', '.vscode', 
        'data/bbm.db', # 不打包本地数据库，到新环境重新生成或手动迁移
        '.DS_Store'
    }
    
    print(f"正在创建部署包: {zip_filename} ...")
    
    with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # 遍历 backend 目录
        for root, dirs, files in os.walk(base_dir):
            # 修改 dirs 列表以排除不需要的文件夹（原地修改生效）
            dirs[:] = [d for d in dirs if d not in excludes]
            
            for file in files:
                if file in excludes or file.endswith('.pyc'):
                    continue
                
                file_path = os.path.join(root, file)
                # 在压缩包内的路径（保持相对结构）
                arcname = os.path.relpath(file_path, start='.')
                
                print(f"添加: {arcname}")
                zipf.write(file_path, arcname)
    
    print(f"\n✅ 打包完成！请将 {zip_filename} 发送到您的 Mac 电脑。")

if __name__ == "__main__":
    pack_project()
