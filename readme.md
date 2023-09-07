# ChatGPT Article Writer
A SEO friendly openai powered article writer to boost your niche.\
This script take a csv file with keywords with respective serial number then generate Article for you
<br>

# Output Structure
All articles are saved as **Word Document**.\
You can set the variable ```DEBUG = True``` in ```gpt_writer.py``` to get output the **MARKDOWN** file alongside with **Word Document**
# CSV file structure
You must have a ```keywords.csv``` file in project directory.

| SL | Keywords  | Title |
|----|-----------|-------|
| 1  | Keyword 1 | title 1|
| 2  | Keyword 2 | title 2|
| .. | ......... | .......|

  
# Versioning 
This script has two versions
- Generate Article from Keywords [v1]
- Generate Article from Outlines [v3]
    * To use this version you must have a ```outlines.csv``` file generated in version [v2]

# Configurations

You need to rename the file ```configs.example.py``` to ```configs.py``` and put your openai api key there.

# Usage
Open your terminal in project directory ```gpt_writer```
Now run the script using the command:\
In Windows:\
```python gpt_writer.py```\
In Linux or Mac:\
```python3 gpt_writer.py```

```Choose Version:
[1] Press 1 for v1 --> For generating article directly
[2] Press 2 for v2 -> For generatining outlines.csv
[3] Press 3 for v3 --> For generating from outlines.csv
[4] Press q for 
    quit
```

Made with ❤️ by [Mahbub Rahman](https://facebook.com/rmahbub01)