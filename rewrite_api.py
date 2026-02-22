import re

path = "/Users/zhanghao/yangyun/Code_Projects/valuation-radar-ui/api_client.py"
with open(path, "r") as f:
    content = f.read()

# Replace the broken except block
pattern = re.compile(r"    except Exception as e:.*?        return pd\.DataFrame\(\)", re.DOTALL)

new_code = """    except Exception as e:
        return pd.DataFrame()"""

content = pattern.sub(new_code, content)

with open(path, "w") as f:
    f.write(content)
