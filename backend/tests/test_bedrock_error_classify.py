from app.jarvis.bedrock_client import classify_bedrock_error


def test_classify_operation_not_allowed():
    assert classify_bedrock_error(RuntimeError("An error occurred (ValidationException) when calling the InvokeModel operation: Operation not allowed")) == "account_restriction"


def test_classify_iam_denied():
    assert classify_bedrock_error(RuntimeError("An error occurred (AccessDeniedException) when calling the InvokeModel operation: User is not authorized to perform: bedrock:InvokeModel")) == "iam_denied"


def test_classify_model_not_found():
    assert classify_bedrock_error(RuntimeError("An error occurred (ResourceNotFoundException) when calling the InvokeModel operation")) == "model_not_found"


def test_classify_other():
    assert classify_bedrock_error(TimeoutError("timed out")) == "request_failed"
