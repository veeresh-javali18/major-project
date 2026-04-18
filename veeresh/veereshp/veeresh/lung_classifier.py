from transformers import pipeline

classifier = pipeline(
    "image-classification",
    model="nicehorse/lung-disease-classification"  # or see models below
)

result = classifier("your_ct_scan.jpg")
print(result)