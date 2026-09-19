"""真实LangChain接口示例；无付费模型。v4运行状态见validation/report.md。"""
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import StrOutputParser

def scripted_model(prompt_value):
    messages = prompt_value.to_messages()
    return AIMessage(content="fixture: " + str(messages[-1].content))

def main():
    prompt = ChatPromptTemplate.from_messages([("system", "Use fixture data only."), ("human", "{task}")])
    chain = prompt | RunnableLambda(scripted_model) | StrOutputParser()
    result = chain.invoke({"task": "explain pagination"})
    assert result == "fixture: explain pagination"
    print(result)

if __name__ == "__main__":
    main()
