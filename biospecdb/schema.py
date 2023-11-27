import graphene

import uploader.schema


class Query(uploader.schema.Query, graphene.ObjectType):
    ...


schema = graphene.Schema(query=Query)
