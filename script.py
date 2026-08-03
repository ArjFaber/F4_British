import time
import requests
from io import BytesIO
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pdfplumber
import os
from urllib.parse import urlparse
import pandas as pd 
import psycopg2
import easyocr

import json
from io import StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup
from pathlib import Path
import random 
  
def obtain_tables_wiki():
    
    years = [2022, 2023, 2024, 2025,2026]
    combined_df = None
    for y in years:
        print("Year: ", y)
        page_url = f"https://en.wikipedia.org/wiki/{y}_F4_British_Championship"

        html = crawl(page_url, 30)

        article, tables = scrape_article(html)
        article["source_url"] = page_url
        article["license"] = "CC BY-SA 4.0"

        with open("wikipedia.json", "w", encoding="utf-8") as f:
            json.dump(article, f, indent=2, ensure_ascii=False)

        

        for i, df in enumerate(tables):
        
            # Append metadata columns
            df["year"] = y
            df["table_index"] = i
            df["source_url"] = page_url
            df["license"] = "CC BY-SA 4.0"

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
                print(df.columns)
            #if len(df.columns) == 7:  # originally 3 + 4 metadata columns
                #df.to_csv(f"wikipedia_table_team_standing_{i}_{y}.csv", index=False)
            #    combined_df = send_to_database(df,page_url,combined_df,str(i))

            if len(df.columns) > 20:  # originally >20
                #df.to_csv(f"wikipedia_table_results_{i}_{y}.csv", index=False)
                try:
                    combined_df = send_to_database(df,page_url,combined_df,str(i))
                except:
                    print("skipped")
            elif len(df.columns) == 16:  # originally 12 + 4 metadata columns
                #df.to_csv(f"wikipedia_table_team_standing_{i}_{y}.csv", index=False)
                try:
                    combined_df = send_to_database(df,page_url,combined_df,str(i))
                except:
                    print("skipped")

    return combined_df


def crawl(url, t):
    time.sleep(t + random.uniform(0, 3))
    headers = {
    "User-Agent": (
        "F4ResultsBritishBot/1.0 "
        "(https://github.com/arjfaber; arjan-faber@hotmail.com)"
    )
    }

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    time.sleep(t)
    return response.text 


def scrape_article(html):
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title = soup.find("h1", id="firstHeading").get_text(strip=True)

    # Main content
    content = soup.find("div", class_="mw-parser-output")

    # First paragraphs
    summary = []
    for p in content.find_all("p", recursive=False):
        text = p.get_text(" ", strip=True)
        if text:
            summary.append(text)
        if len(summary) >= 3:
            break

    # Section headings
    sections = []
    for tag in content.find_all(["h2", "h3"]):
        headline = tag.find("span", class_="mw-headline")
        if headline:
            sections.append(headline.get_text(strip=True))

    # Infobox
    infobox = {}
    box = soup.find("table", class_="infobox")
    if box:
        for row in box.find_all("tr"):
            label = row.find("th")
            data = row.find("td")
            if label and data:
                infobox[label.get_text(" ", strip=True)] = data.get_text(
                    " ", strip=True
                )

    # Wikitables
    tables = []
    for node in soup.find_all("table", class_="wikitable"):
        try:
            df = pd.read_html(StringIO(str(node)))[0]
            tables.append(df)
        except Exception:
            pass

    return {
        "title": title,
        "summary": " ".join(summary),
        "sections": sections,
        "infobox": infobox,
    }, tables

def clean_columns(df):
    # remove duplicated column names
    df = df.loc[:, ~df.columns.duplicated()]

    # remove completely empty columns
    df = df.dropna(axis=1, how="all")

    return df


def find_driver_column(df):
    for col in df.columns:
        if "driver" in str(col).lower():
            return col
    return None

def send_to_database(df, page_url, combined_df, tab):

    driver_col = find_driver_column(df)

    if driver_col:
        df = df.rename(columns={driver_col: "Driver"})
        key = "Driver"

    elif "Team" in df.columns:
        key = "Team"

    else:
        print("Skipping table")
        print(df.columns.tolist())
        return combined_df

    df = clean_columns(df)

    # First valid table becomes the base dataframe
    if combined_df is None:
        return df

    combined_df = clean_columns(combined_df)

    suffix = "_" + str(page_url) + "_tab_" + tab

    combined_df = pd.merge(
        combined_df,
        df,
        on=["Driver", "year"],
        how="outer",
        suffixes=("", suffix)
    )

    return clean_columns(combined_df)
combined_df = obtain_tables_wiki()
combined_df = combined_df.loc[:, ~combined_df.columns.duplicated()]
import re

def make_unique_columns(columns, max_length=63):
    new_columns = []
    seen = {}

    for col in columns:
        # Clean characters
        col = str(col).lower()
        col = re.sub(r'[^a-z0-9_]', '_', col)
        col = col.strip('_')

        # Truncate
        col = col[:max_length]

        # Handle duplicates
        if col in seen:
            seen[col] += 1
            suffix = f"_{seen[col]}"
            col = col[:max_length - len(suffix)] + suffix
        else:
            seen[col] = 0

        new_columns.append(col)

    return new_columns

combined_df.columns = make_unique_columns(combined_df.columns)

conn = psycopg2.connect(
            host="ep-long-glitter-at9v26w9-pooler.c-9.us-east-1.aws.neon.tech",
            database="neondb",
            user="neondb_owner",
            password="npg_P6OimSTt9ngC",
            port=5432,
            sslmode="require"
        )
cur = conn.cursor()

table_name = "f4_british_results"


# Remove existing table
cur.execute(f'DROP TABLE IF EXISTS "{table_name}";')
conn.commit()


# Create table dynamically
columns = combined_df.columns.tolist()

column_definitions = ", ".join(
    f'"{col}" TEXT'
    for col in columns
)

cur.execute(f"""
CREATE TABLE "{table_name}" (
    {column_definitions}
);
""")

conn.commit()


# Insert data dynamically
column_names = ", ".join(
    f'"{col}"'
    for col in columns
)

placeholders = ", ".join(
    ["%s"] * len(columns)
)

insert_query = f"""
INSERT INTO "{table_name}" ({column_names})
VALUES ({placeholders})
"""


# Convert NaN -> None for PostgreSQL NULL
data = combined_df.where(
    pd.notnull(combined_df),
    None
).values.tolist()


# Safety check
assert all(
    len(row) == len(columns)
    for row in data
), "Column/value mismatch"


cur.executemany(
    insert_query,
    data
)

conn.commit()

cur.close()
conn.close()
print(combined_df.groupby("year").size())
print(f"Imported {len(combined_df)} rows into {table_name}")
