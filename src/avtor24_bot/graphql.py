from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .http import GraphQLClient, GraphQLRequest


GET_AUCTION_WITH_CONSTRAINTS = """
query GetAuctionWithConstraints($skip: Int, $limit: Int, $filter: AuctionFilterInputType, $constraintsFilter: AuctionFilterInputType, $pagination: AuctionPaginationInputType) {
  auctionFilterConstraint(filter: $constraintsFilter) {
    minCountBid
    maxCountBid
    minUniqueValue
    maxUniqueValue
    minDeadline
    maxDeadline
    minBudget
    maxBudget
    __typename
  }
  auctionFilteredCount(filter: $filter)
  orders(skip: $skip, limit: $limit, filter: $filter, pagination: $pagination) {
    total
    captcha
    pages
    orders {
      ...orderDataFragment
      __typename
    }
    __typename
  }
  recommendedOrdersForExpert(limit: $limit) {
    orders {
      ...orderDataFragment
      __typename
    }
    __typename
  }
}

fragment orderDataFragment on order {
  id
  type {
    id
    name
    __typename
  }
  category {
    id
    name
    __typename
  }
  customer {
    id
    isOnline
    isTelegramEnabled
    nickName
    __typename
  }
  badges {
    id
    name
    __typename
  }
  title
  description
  budget
  recommendedBudget
  isFavorite
  isConsult
  isInviteOrder
  isPremium
  isHidden
  isPaid
  isRead
  creation
  deadline
  customerFiles {
    id
    name
    path
    hash
    sizeInMb
    readableCreationUnixtime
    type
    __typename
  }
  authorFiles {
    id
    __typename
  }
  countOffers
  isMatchFilter
  isMatchQualification
  authorHasOffer
  isExpressOrder
  authorOffer {
    id
    origin_bid
    bid
    text
    __typename
  }
  __typename
}
"""

GET_ORDER_FOR_BID = """
query getOrderForBid($orderId: ID!) {
  order(id: $orderId) {
    id
    isExpressOrder
    budget
    title
    type {
      id
      name
      __typename
    }
    category {
      id
      name
      __typename
    }
    authorOffer {
      id
      bid
      origin_bid
      text
      expired
      __typename
    }
    countOffers
    currentAuthorBidWasHidden
    customer {
      orderTaxPercent
      __typename
    }
    finalBidFormula
    performerGetFormula
    performerTaxFormula
    __typename
  }
}
"""

GET_BID_PARAMS = """
query getBidParams($orderId: ID!, $typeId: ID!, $categoryId: ID!, $typeIdInt: Int!, $categoryIdInt: Int!, $isFirstOffer: Boolean = false) {
  predictBid(orderId: $orderId) @include(if: $isFirstOffer)
  graph: bidsgraphdata(typeId: $typeId, categoryId: $categoryId) {
    date {
      year
      month
      __typename
    }
    min
    avg
    max
    __typename
  }
  getOrderParams(typeId: $typeIdInt, subjectId: $categoryIdInt) {
    recommendPrice
    __typename
  }
}
"""

MARK_ORDER_AS_READ = """
mutation readOrder($id: ID!) {
  orderMarkAsRead(id: $id)
}
"""

MAKE_OFFER = """
mutation makeOffer($orderId: ID!, $bid: Int, $message: EscapeString, $expired: String, $scenario: RecommendedScenarioEnum, $captchaToken: String) {
  orderCreateOffer(
    id: $orderId
    bid: $bid
    message: $message
    expired: $expired
    subscribe: false
    recommendedScenario: $scenario
    captchaToken: $captchaToken
  ) {
    id
    origin_bid
    bid
    text
    expired
    countOffersOfOrder
    __typename
  }
}
"""

ADD_COMMENT = """
mutation addComment($orderId: ID!, $text: String!) {
  addComment(orderId: $orderId, text: $text) {
    __typename
    ...messageFragment
  }
}

fragment messageFragment on message {
  id
  user_id
  text
  creation
  isAdminComment
  isAutoHidden
  isRead
  watched
  files {
    id
    name
    hash
    type
    path
    sizeInMb
    isFinal
    __typename
  }
  __typename
}
"""


async def fetch_orders(
    client: GraphQLClient,
    *,
    limit: int,
    page: int,
    filters: Dict[str, Any],
    constraints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    request = GraphQLRequest(
        operation_name="GetAuctionWithConstraints",
        query=GET_AUCTION_WITH_CONSTRAINTS,
        variables={
            "skip": 0,
            "limit": limit,
            "filter": filters,
            "constraintsFilter": constraints or filters,
            "pagination": {"pageTo": page},
        },
    )
    return await client.execute(request)


async def mark_order_as_read(client: GraphQLClient, order_id: str) -> bool:
    data = await client.execute(
        GraphQLRequest(
            operation_name="readOrder",
            query=MARK_ORDER_AS_READ,
            variables={"id": order_id},
        )
    )
    return bool(data.get("orderMarkAsRead"))


async def get_order_for_bid(client: GraphQLClient, order_id: str) -> Dict[str, Any]:
    data = await client.execute(
        GraphQLRequest(
            operation_name="getOrderForBid",
            query=GET_ORDER_FOR_BID,
            variables={"orderId": order_id},
        )
    )
    return data.get("order", {})


async def get_bid_params(
    client: GraphQLClient,
    *,
    order_id: str,
    type_id: str,
    category_id: str,
    is_first_offer: bool,
) -> Dict[str, Any]:
    type_id_int = int(type_id)
    category_id_int = int(category_id)
    data = await client.execute(
        GraphQLRequest(
            operation_name="getBidParams",
            query=GET_BID_PARAMS,
            variables={
                "orderId": order_id,
                "typeId": type_id,
                "categoryId": category_id,
                "typeIdInt": type_id_int,
                "categoryIdInt": category_id_int,
                "isFirstOffer": is_first_offer,
            },
        )
    )
    return data


async def make_offer(
    client: GraphQLClient,
    *,
    order_id: str,
    bid: int,
    message: str,
    captcha_token: Optional[str],
    scenario: Optional[str] = None,
    expired: Optional[str] = None,
) -> Dict[str, Any]:
    data = await client.execute(
        GraphQLRequest(
            operation_name="makeOffer",
            query=MAKE_OFFER,
            variables={
                "orderId": order_id,
                "bid": bid,
                "message": message,
                "expired": expired,
                "scenario": scenario,
                "captchaToken": captcha_token,
            },
        )
    )
    return data.get("orderCreateOffer", {})


async def add_comment(client: GraphQLClient, order_id: str, text: str) -> Dict[str, Any]:
    data = await client.execute(
        GraphQLRequest(
            operation_name="addComment",
            query=ADD_COMMENT,
            variables={"orderId": order_id, "text": text},
        )
    )
    return data.get("addComment", {})
