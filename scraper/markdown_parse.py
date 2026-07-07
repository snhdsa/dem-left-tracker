import sys
import re

def main(markdown_location):
    f = open(markdown_location, "r")
    read_text = f.read()

    pattern = re.compile(r"\*\*(R|O)-(\d{0,3}-\d{0,4})\*\*((?!\*\*R-).)*?\*\*MOTION (FAILED|CARRIED)\*\*", re.S|re.M)
    results = pattern.finditer(read_text)    

    for match in results:
        #Finding Reso Number
        reso_number = re.search(r"\*\*(R|O)-(\d{0,3}-\d{0,4})\*\*", match.group()).group(0)
        print(reso_number)

        #Finding Endorsers
        endorsers = []
        try:
            endorsers_list = re.search(r"(?<=Endorser:\s)[^\n|\*]*", match.group(), re.S|re.M).group(0)
            endorser = re.finditer(r"(?:(?<=Alderman\s)|(?<=Alderman-at-Large\s))([A-Z][a-z]+\s+[A-Z][a-z]+)", endorsers_list)
            for e in endorser:
                endorsers.append(e.group())
        except: 
            endorsers_list = "N/A"
        
        print("Endorsers: ", endorsers)

        #Resolution Summary
        try:
            reso_summary = re.findall(r"\*\*.*\*\*", match.group())[1]
        except:
            reso_summary = "N/A"
        print("Summary: ", reso_summary)

        #YEAS/NAYS
        yeas = []
        nays = []
        try:
            yeas_list = re.search(r"(?<=Yea:\s)[^\d]*", match.group(), re.S|re.M).group(0)
            yeas_find = re.findall(r"(?:Alderman|Alderwoman)(?:-at-Large)?\s+([A-Za-z’]+)", yeas_list)
            for yea in yeas_find:
                yeas.append(yea)
        except: 
            yeas_list = "N/A"

        try:
            nays_list = re.search(r"(?<=Nay:\s)[^\d]*", match.group(), re.S|re.M).group(0)
            nays_find = re.findall(r"(?:Alderman|Alderwoman)(?:-at-Large)?\s+([A-Za-z’]+)", nays_list)
            for nay in nays_find:
                nays.append(nay)
        except: 
            nays_list = "N/A"

        print("yeas: ", yeas)
        print("nays: ", nays)
        print("\n\n")

    #\*\*[RO]-(\d{0,3}-\d{0,4})\*\*((?!\*\*R-).)*?MOTION (FAILED|CARRIED)\*\*



if __name__ == "__main__":
    pdf_location = str(sys.argv[1])
    main(pdf_location)