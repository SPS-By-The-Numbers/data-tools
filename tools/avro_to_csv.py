from fastavro import reader
import csv

head = True
count = 0
f = csv.writer(open("moo.csv", "w+"))
with open('expenditures.avro', 'rb') as fo:
    avro_reader = reader(fo)
    for emp in avro_reader:
        #print(emp)
        if head == True:
            header = emp.keys()
            f.writerow(header)
            head = False
        count += 1
        f.writerow(emp.values())
print(count)
