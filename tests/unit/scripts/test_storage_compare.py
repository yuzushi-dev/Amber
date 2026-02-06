from scripts.storage_compare import compare_records


def test_compare_records_detects_missing_and_mismatch():
    src = [
        {"bucket": "documents", "key": "a.txt", "size": 10, "etag": "x"},
        {"bucket": "documents", "key": "b.txt", "size": 20, "etag": "y"},
    ]
    dst = [
        {"bucket": "documents", "key": "a.txt", "size": 11, "etag": "x"},
    ]

    report = compare_records(src, dst)

    assert report["missing_in_dst"] == 1
    assert report["extra_in_dst"] == 0
    assert report["mismatched"] == 1


def test_compare_records_no_diff():
    src = [
        {
            "bucket": "documents",
            "key": "same.txt",
            "size": 5,
            "etag": "abc",
            "sha256": "def",
        }
    ]
    dst = [
        {
            "bucket": "documents",
            "key": "same.txt",
            "size": 5,
            "etag": "abc",
            "sha256": "def",
        }
    ]

    report = compare_records(src, dst)

    assert report["missing_in_dst"] == 0
    assert report["extra_in_dst"] == 0
    assert report["mismatched"] == 0
